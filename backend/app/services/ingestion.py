"""Module 1 — Data ingestion: TMDb → Postgres.

Pulls popular + top-rated movies, fetches full detail and keywords for each,
and upserts them into the ``movies`` table (matched on ``tmdb_id`` so re-runs
never duplicate rows).

CLI usage (from ``backend/``):

    python -m app.services.ingestion --pages 20

Design:
- ``TMDbClient`` is rate-limit aware: on HTTP 429/5xx it sleeps with
  exponential backoff (honoring ``Retry-After`` when TMDb sends it) instead of
  hammering the API. TMDb's limit is ~50 req/s; we stay well under it by
  working sequentially.
- One movie failing (404, malformed payload, network error after retries)
  skips that movie and never aborts the run — every failure is logged.
- Each ingested movie commits immediately, so a Ctrl-C mid-run keeps progress.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import random
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import httpx
from sqlalchemy import case, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.models import Movie

logger = logging.getLogger("app.ingestion")

TMDB_BASE_URL = "https://api.themoviedb.org/3"

# Backoff behaviour (kept as module constants so tests can reason about them).
_MAX_RETRIES = 5
_BACKOFF_BASE_SECONDS = 0.5


class TMDbError(RuntimeError):
    """Raised when a TMDb request fails for a non-retryable reason."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class IngestStats:
    """Result summary for one ingestion run."""

    pages_per_list: int = 0
    discovered: int = 0
    succeeded: int = 0
    failed: int = 0
    duration_seconds: float = 0.0
    failed_ids: list[int] = field(default_factory=list)


class TMDbClient:
    """Small typed wrapper around the TMDb v3 endpoints we need.

    Works with both auth styles: a v3 ``api_key`` (query parameter) and a v4
    read-access token (JWT string, sent as a Bearer header).
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = TMDB_BASE_URL,
        timeout_seconds: float = 10.0,
        max_retries: int = _MAX_RETRIES,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise TMDbError("TMDb API key is empty. Set TMDB_API_KEY in backend/.env")
        # INFO request URLs would expose a v3 key in the query string.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        self._uses_bearer = api_key.startswith("eyJ")
        self._bearer = api_key if self._uses_bearer else None
        self._api_key = None if self._uses_bearer else api_key
        self._max_retries = max(1, min(max_retries, _MAX_RETRIES))
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout_seconds,
            headers={"accept": "application/json"},
            transport=transport,
        )

    async def __aenter__(self) -> TMDbClient:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Release the underlying HTTP connection pool."""
        await self._client.aclose()

    async def _get(self, path: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """GET a TMDb path with rate-limit-aware exponential backoff."""
        merged: dict[str, Any] = dict(params or {})
        if self._api_key is not None:
            merged["api_key"] = self._api_key

        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                response = await self._client.get(
                    path,
                    params=merged,
                    headers=(
                        {"Authorization": f"Bearer {self._bearer}"} if self._uses_bearer else None
                    ),
                )
            except httpx.HTTPError as exc:  # Never retain a credential-bearing URL.
                last_error = TMDbError(type(exc).__name__)
                await self._sleep_backoff(attempt)
                continue

            if response.status_code == httpx.codes.TOO_MANY_REQUESTS or (
                response.status_code >= 500
            ):
                last_error = TMDbError(f"TMDb returned {response.status_code} for {path}")
                await self._sleep_backoff(attempt, retry_after=response.headers.get("Retry-After"))
                continue

            if response.status_code >= 400:
                raise TMDbError(
                    f"TMDb returned {response.status_code} for {path}",
                    status_code=response.status_code,
                )
            payload: dict[str, Any] = response.json()
            return payload

        raise TMDbError(f"Gave up on {path} after {self._max_retries} attempts: {last_error}")

    async def _sleep_backoff(self, attempt: int, retry_after: str | None = None) -> None:
        """Sleep exponentially longer per attempt, honoring Retry-After."""
        if retry_after is not None:
            try:
                await asyncio.sleep(min(5.0, max(0.0, float(retry_after))))
                return
            except ValueError:
                pass  # malformed header — fall back to exponential backoff
        delay = _BACKOFF_BASE_SECONDS * (2**attempt) + random.uniform(0, 0.25)
        await asyncio.sleep(delay)

    # --- Public endpoint helpers -------------------------------------------

    async def discover_popular(self, page: int) -> list[dict[str, Any]]:
        """One page of movies sorted by popularity."""
        payload = await self._get(
            "/discover/movie",
            {
                "sort_by": "popularity.desc",
                "include_adult": "false",
                "page": page,
            },
        )
        return list(payload.get("results", []))

    async def top_rated(self, page: int) -> list[dict[str, Any]]:
        """One page of the top-rated list."""
        payload = await self._get("/movie/top_rated", {"page": page})
        return list(payload.get("results", []))

    async def released_movies(
        self, page: int, *, since: date | None = None
    ) -> list[dict[str, Any]]:
        """Popular released films, optionally restricted to a recent date range."""
        params: dict[str, Any] = {
            "sort_by": "popularity.desc",
            "include_adult": "false",
            "include_video": "false",
            "primary_release_date.lte": date.today().isoformat(),
            "vote_count.gte": 20,
            "page": page,
        }
        if since is not None:
            params["primary_release_date.gte"] = since.isoformat()
        payload = await self._get("/discover/movie", params)
        return list(payload.get("results", []))

    async def movie_detail(self, tmdb_id: int) -> dict[str, Any]:
        """Full movie detail (genres with names, runtime, ...)."""
        return await self._get(f"/movie/{tmdb_id}")

    async def search_movies(self, title: str) -> list[dict[str, Any]]:
        payload = await self._get("/search/movie", {"query": title, "include_adult": "false"})
        return list(payload.get("results", []))

    async def movie_bundle(self, tmdb_id: int) -> dict[str, Any]:
        """Fetch details and keywords together, including real poster paths."""
        return await self._get(f"/movie/{tmdb_id}", {"append_to_response": "keywords"})

    async def movie_keywords(self, tmdb_id: int) -> dict[str, Any]:
        """Keyword list for a movie."""
        return await self._get(f"/movie/{tmdb_id}/keywords")


def movie_row_from_tmdb(detail: Mapping[str, Any], keywords: Mapping[str, Any]) -> dict[str, Any]:
    """Map a TMDb detail + keywords payload to a ``movies`` table row."""
    release_date = str(detail.get("release_date") or "")
    genres = detail.get("genres") or []
    keyword_items = keywords.get("keywords") or []
    return {
        "tmdb_id": int(detail["id"]),
        "title": str(detail.get("title") or detail.get("original_title") or "Untitled"),
        "overview": detail.get("overview") or None,
        "release_year": int(release_date[:4]) if len(release_date) >= 4 else None,
        "runtime": detail.get("runtime") or None,
        "genres": [str(g["name"]) for g in genres if g.get("name")],
        "keywords": [str(k["name"]) for k in keyword_items if k.get("name")],
        "language": detail.get("original_language"),
        "poster_path": detail.get("poster_path"),
        "vote_average": detail.get("vote_average"),
        "vote_count": detail.get("vote_count"),
        "popularity": detail.get("popularity"),
        # Module 7 will fill personality; ingestion leaves it empty.
        "personality": None,
        "tmdb_checked_at": datetime.now(UTC),
        "tmdb_synced_at": datetime.now(UTC),
    }


_UPDATABLE_COLUMNS = (
    "title",
    "overview",
    "release_year",
    "runtime",
    "genres",
    "keywords",
    "language",
    "poster_path",
    "vote_average",
    "vote_count",
    "popularity",
    "personality",
    "tmdb_checked_at",
    "tmdb_synced_at",
)


async def upsert_movie(session: AsyncSession, row: Mapping[str, Any]) -> None:
    """Insert a movie row, or update the existing one matched on tmdb_id."""
    await upsert_movies(session, [row])


async def upsert_movies(session: AsyncSession, rows: list[Mapping[str, Any]]) -> None:
    """Bulk upsert public metadata while preserving IDs, ratings and personality."""
    if not rows:
        return
    statement = pg_insert(Movie).values([dict(row) for row in rows])
    content_changed = (
        Movie.title.is_distinct_from(statement.excluded.title)
        | Movie.overview.is_distinct_from(statement.excluded.overview)
        | Movie.genres.is_distinct_from(statement.excluded.genres)
        | Movie.keywords.is_distinct_from(statement.excluded.keywords)
    )
    statement = statement.on_conflict_do_update(
        index_elements=[Movie.__table__.c.tmdb_id],
        set_={
            **{column: statement.excluded[column] for column in _UPDATABLE_COLUMNS},
            "personality": func.coalesce(statement.excluded.personality, Movie.personality),
            "tmdb_checked_at": func.coalesce(
                statement.excluded.tmdb_checked_at, Movie.tmdb_checked_at
            ),
            "tmdb_synced_at": func.coalesce(
                statement.excluded.tmdb_synced_at, Movie.tmdb_synced_at
            ),
            "embedding": case((content_changed, None), else_=Movie.embedding),
            "updated_at": func.now(),
        },
    )
    await session.execute(statement)


async def ingest_movies(
    pages: int,
    *,
    client: TMDbClient | None = None,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
) -> IngestStats:
    """Pull ``pages`` pages of popular + top-rated movies and upsert them.

    Errors on a single movie (fetch, parse, or write) skip that movie; errors
    on a list page itself abort the run — partial lists are retried next run.
    """
    if pages < 1:
        raise ValueError("pages must be >= 1")

    stats = IngestStats(pages_per_list=pages)
    started = time.monotonic()
    owns_client = client is None
    if client is None:
        client = TMDbClient(api_key=get_settings().tmdb_api_key)
    session_factory = sessionmaker or get_sessionmaker()

    try:
        # 1) Collect candidate movies from both lists, deduplicated by id.
        candidates: dict[int, dict[str, Any]] = {}
        for page in range(1, pages + 1):
            popular = await client.discover_popular(page)
            top_rated = await client.top_rated(page)
            for list_item in (*popular, *top_rated):
                tmdb_id = int(list_item["id"])
                candidates.setdefault(tmdb_id, list_item)
        stats.discovered = len(candidates)
        logger.info("Discovered %d unique movies from %d pages per list", len(candidates), pages)

        # 2) Fetch detail + keywords per movie and upsert, skipping failures.
        for position, (tmdb_id, _list_item) in enumerate(candidates.items(), start=1):
            try:
                detail = await client.movie_detail(tmdb_id)
                keywords = await client.movie_keywords(tmdb_id)
                row = movie_row_from_tmdb(detail, keywords)
            except (TMDbError, KeyError, TypeError, ValueError) as exc:
                stats.failed += 1
                stats.failed_ids.append(tmdb_id)
                logger.warning(
                    "[%d/%d] skipping tmdb_id=%d: %s", position, len(candidates), tmdb_id, exc
                )
                continue

            try:
                async with session_factory() as session:
                    await upsert_movie(session, row)
                    await session.commit()
            except Exception as exc:  # noqa: BLE001 — one bad row must not kill the run
                stats.failed += 1
                stats.failed_ids.append(tmdb_id)
                logger.warning(
                    "[%d/%d] database write failed for tmdb_id=%d: %s",
                    position,
                    len(candidates),
                    tmdb_id,
                    type(exc).__name__,
                )
                continue

            stats.succeeded += 1
            if position % 10 == 0 or position == len(candidates):
                logger.info(
                    "%d/%d movies ingested (%d failed so far)",
                    position,
                    len(candidates),
                    stats.failed,
                )
    finally:
        if owns_client:
            await client.aclose()

    stats.duration_seconds = time.monotonic() - started
    return stats


def _parse_args(argv: Iterable[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.services.ingestion",
        description="Ingest popular + top-rated movies from TMDb into Postgres.",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=5,
        help="Pages to pull per list (popular and top-rated); default: 5",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log verbosity; default: INFO",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    """CLI entrypoint. Returns a process exit code."""
    args = _parse_args(argv)
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    stats = asyncio.run(ingest_movies(pages=args.pages))
    logger.info(
        "Done: %d ingested, %d failed, %d discovered, in %.1fs",
        stats.succeeded,
        stats.failed,
        stats.discovered,
        stats.duration_seconds,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
