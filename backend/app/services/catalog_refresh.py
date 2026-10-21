"""Refresh the catalog once, or run daily in a dedicated maintenance process.

Run from backend: python -m app.services.catalog_refresh --limit 6000 --pages 10
Committed batches survive interruptions. No public endpoint can start bulk work.
"""

import argparse
import asyncio
import json
import logging
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select, update

from app.core.config import get_settings
from app.core.db import dispose_engine, get_sessionmaker
from app.models import Movie
from app.services.ingestion import TMDbClient, TMDbError, movie_row_from_tmdb, upsert_movies

logger = logging.getLogger("app.catalog_refresh")
BATCH_SIZE = 25
FETCH_CONCURRENCY = 8


@dataclass
class RefreshReport:
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    finished_at: str | None = None
    discovered: int = 0
    selected: int = 0
    updated: int = 0
    unavailable: list[int] = field(default_factory=list)
    failed: list[int] = field(default_factory=list)


def eligible_release(detail: Mapping[str, Any], today: date) -> bool:
    """Keep adult, undated and future releases out of newly discovered rows."""
    if detail.get("adult"):
        return False
    try:
        return date.fromisoformat(str(detail.get("release_date", ""))) <= today
    except ValueError:
        return False


async def fetch_batch(
    client: TMDbClient, ids: list[int], existing: set[int], report: RefreshReport
) -> list[Mapping[str, Any]]:
    """Bound in-flight requests; pacing also bounds very fast responses."""
    semaphore = asyncio.Semaphore(FETCH_CONCURRENCY)

    async def fetch(tmdb_id: int) -> Mapping[str, Any] | None:
        async with semaphore:
            try:
                detail = await client.movie_bundle(tmdb_id)
                if int(detail["id"]) != tmdb_id:
                    raise ValueError("Mismatched TMDb response")
                if detail.get("adult") or (
                    tmdb_id not in existing and not eligible_release(detail, date.today())
                ):
                    report.unavailable.append(tmdb_id)
                    return None
                return movie_row_from_tmdb(detail, detail.get("keywords", {}))
            except TMDbError as exc:
                if exc.status_code in (401, 403):
                    raise  # Stop rather than checkpointing an invalid credential as movie failures.
                target = report.unavailable if exc.status_code == 404 else report.failed
                target.append(tmdb_id)
                return None
            except (ValueError, TypeError, KeyError):
                report.failed.append(tmdb_id)
                return None
            finally:
                await asyncio.sleep(0.2)

    results = await asyncio.gather(*(fetch(tmdb_id) for tmdb_id in ids))
    return [row for row in results if row is not None]


async def save_batch(rows: list[Mapping[str, Any]], checked_ids: list[int]) -> None:
    """Metadata and attempt checkpoints commit together; database errors abort the run."""
    async with get_sessionmaker()() as session:
        await upsert_movies(session, rows)
        if checked_ids:
            await session.execute(
                update(Movie)
                .where(Movie.tmdb_id.in_(checked_ids))
                .values(tmdb_checked_at=datetime.now(UTC))
            )
        await session.commit()


async def refresh_catalog(
    *, limit: int = 500, pages: int = 5, stale_days: int = 7
) -> RefreshReport:
    if not 1 <= limit <= 10000 or not 1 <= pages <= 50 or not 1 <= stale_days <= 365:
        raise ValueError("Use limit 1–10000, pages 1–50 and stale-days 1–365")
    report = RefreshReport()
    cutoff = datetime.now(UTC) - timedelta(days=stale_days)
    try:
        async with get_sessionmaker()() as session:
            existing = set((await session.execute(select(Movie.tmdb_id))).scalars().all())
            stale = list(
                (
                    await session.execute(
                        select(Movie.tmdb_id)
                        .where(or_(Movie.tmdb_checked_at.is_(None), Movie.tmdb_checked_at < cutoff))
                        .order_by(
                            Movie.tmdb_checked_at.asc().nullsfirst(),
                            Movie.vote_count.desc().nullslast(),
                            Movie.tmdb_id,
                        )
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        async with TMDbClient(get_settings().tmdb_api_key) as client:
            discovered: dict[int, None] = {}
            for page in range(1, pages + 1):
                lists = (
                    await client.released_movies(page),
                    await client.released_movies(page, since=date.today() - timedelta(days=730)),
                    await client.top_rated(page),
                )
                for items in lists:
                    for item in items:
                        if eligible_release(item, date.today()):
                            discovered[int(item["id"])] = None
            report.discovered = len(discovered)
            # Reserve room for both new releases and older unchecked rows on bounded runs.
            new_ids = [tmdb_id for tmdb_id in discovered if tmdb_id not in existing]
            reserved = new_ids[: max(1, limit // 3)]
            ids = list(dict.fromkeys([*reserved, *stale, *new_ids]))[:limit]
            report.selected = len(ids)
            for start in range(0, len(ids), BATCH_SIZE):
                batch = ids[start : start + BATCH_SIZE]
                rows = await fetch_batch(client, batch, existing, report)
                await save_batch(rows, batch)
                report.updated += len(rows)
                logger.info(
                    "Catalog %d/%d checked; %d updated; %d unavailable; %d failed",
                    start + len(batch),
                    len(ids),
                    report.updated,
                    len(report.unavailable),
                    len(report.failed),
                )
        report.finished_at = datetime.now(UTC).isoformat()
        return report
    finally:
        await dispose_engine()


async def run(args: argparse.Namespace) -> int:
    while True:
        try:
            report = await refresh_catalog(
                limit=args.limit, pages=args.pages, stale_days=args.stale_days
            )
            print(json.dumps(asdict(report)), flush=True)
            result = 1 if report.failed else 0
        except Exception as exc:
            # Database and HTTP exceptions may contain URLs/credentials. Log only the type.
            logger.error(
                "Catalog run aborted (%s); committed batches are retained", type(exc).__name__
            )
            result = 1
        if not args.interval_hours:
            return result
        await asyncio.sleep(args.interval_hours * 3600)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--pages", type=int, default=5)
    parser.add_argument("--stale-days", type=int, default=7)
    parser.add_argument(
        "--interval-hours", type=int, default=0, help="0: run once; otherwise repeat"
    )
    args = parser.parse_args()
    if args.interval_hours < 0:
        parser.error("interval-hours must be nonnegative")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
