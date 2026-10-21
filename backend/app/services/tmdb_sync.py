"""Refresh public movie metadata and resolve referenced TMDb titles.

Explicit CLI sync keeps bulk imports out of the public API. Chat may resolve
up to three missing reference titles; only exact TMDb title matches are saved.
"""

import argparse
import asyncio
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import dispose_engine, get_sessionmaker
from app.models import Movie
from app.services.ingestion import TMDbClient, TMDbError, movie_row_from_tmdb, upsert_movie

logger = logging.getLogger("app.tmdb_sync")


async def _save_refreshed_movie(row: dict[str, Any]) -> None:
    """Retry one idempotent upsert after a managed database disconnect."""
    for attempt in range(2):
        try:
            async with get_sessionmaker()() as session:
                await upsert_movie(session, row)
                await session.commit()
            return
        except (SQLAlchemyError, OSError, TimeoutError):
            await dispose_engine()
            if attempt:
                raise
            await asyncio.sleep(0.5)


async def resolve_references(
    session: AsyncSession,
    titles: list[str],
    *,
    client: TMDbClient | None = None,
) -> None:
    if not titles or (client is None and not get_settings().tmdb_api_key):
        return
    owns_client = client is None
    active_client = client or TMDbClient(
        get_settings().tmdb_api_key,
        timeout_seconds=4,
        max_retries=1,
    )
    try:
        for title in list(dict.fromkeys(titles))[:3]:
            existing = (
                await session.execute(
                    select(Movie.id)
                    .where(
                        func.lower(Movie.title) == title.strip().lower(),
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if existing is not None:
                continue
            matches = await active_client.search_movies(title)
            exact = next(
                (
                    item
                    for item in matches
                    if str(item.get("title", "")).casefold() == title.strip().casefold()
                    and not item.get("adult")
                ),
                None,
            )
            if exact is None:
                continue
            detail = await active_client.movie_bundle(int(exact["id"]))
            await upsert_movie(session, movie_row_from_tmdb(detail, detail.get("keywords", {})))
            await session.flush()
    finally:
        if owns_client:
            await active_client.aclose()


async def refresh_movies(limit: int, *, movie_ids: list[UUID] | None = None) -> tuple[int, int]:
    """Refresh a bounded selection without changing IDs, ratings or profiles."""
    if not 1 <= limit <= 500:
        raise ValueError("Choose between 1 and 500 movies per refresh")
    succeeded = failed = 0
    try:
        async with get_sessionmaker()() as session:
            statement = select(Movie.tmdb_id)
            if movie_ids:
                statement = statement.where(Movie.id.in_(movie_ids))
            else:
                statement = statement.where(Movie.poster_path.is_(None))
            ids = list(
                (
                    await session.execute(
                        statement.order_by(
                            Movie.vote_count.desc().nullslast(),
                            Movie.id,
                        ).limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        async with TMDbClient(get_settings().tmdb_api_key) as client:
            for tmdb_id in ids:
                try:
                    detail = await client.movie_bundle(tmdb_id)
                    await _save_refreshed_movie(
                        movie_row_from_tmdb(detail, detail.get("keywords", {}))
                    )
                    succeeded += 1
                except (TMDbError, ValueError, KeyError, SQLAlchemyError, OSError, TimeoutError):
                    failed += 1
                    logger.warning("Could not refresh TMDb movie %d", tmdb_id)
                logger.info("TMDb refresh progress: %d updated; %d failed", succeeded, failed)
        return succeeded, failed
    finally:
        await dispose_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    success, failures = asyncio.run(refresh_movies(args.limit))
    print(f"TMDb refresh: {success} updated; {failures} failed.")
