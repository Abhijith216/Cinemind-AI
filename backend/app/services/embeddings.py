"""Module 2 — Embedding generation: movies → vectors for semantic search.

Composes a keyword-first text blob per movie (themes matter more than raw
overview — see the product spec), embeds it with an OpenAI-compatible
embeddings endpoint (``text-embedding-3-large`` by default, truncated to
1536 dims to match the ``movies.embedding vector(1536)`` column), and writes
vectors back to Postgres via pgvector's SQLAlchemy type.

CLI usage (from ``backend/``):

    python -m app.services.embeddings --backfill

Resumability: the backfill processes batches of 100 (query movies with
``embedding IS NULL``, ordered by id for a stable order) and commits after
every batch. A crash mid-run loses at most one batch; re-running continues
where it left off. Movies that permanently fail to embed are excluded from
the current run and reported — they stay ``NULL`` and are retried next run.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import random
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.models import EMBEDDING_DIMENSIONS, Movie

logger = logging.getLogger("app.embeddings")

OPENAI_EMBEDDINGS_PATH = "/embeddings"

_MAX_RETRIES = 5
_BACKOFF_BASE_SECONDS = 0.5
_MAX_OVERVIEW_CHARS = 1000


class EmbeddingError(RuntimeError):
    """Raised when the embeddings endpoint fails for a non-retryable reason."""


@dataclass
class EmbeddingStats:
    """Result summary for one backfill run."""

    embedded: int = 0
    failed: int = 0
    remaining: int = 0
    duration_seconds: float = 0.0
    failed_ids: list[Any] = field(default_factory=list)


class EmbeddableMovie(Protocol):
    """Structural type: a Movie ORM instance (or anything shaped like one).

    Declared as read-only properties so any object with matching attributes
    (including SQLAlchemy models) structurally satisfies it.
    """

    @property
    def title(self) -> str | None: ...

    @property
    def overview(self) -> str | None: ...

    @property
    def genres(self) -> list[Any] | None: ...

    @property
    def keywords(self) -> list[Any] | None: ...

    @property
    def release_year(self) -> int | None: ...


def build_embedding_text(movie: EmbeddableMovie) -> str:
    """Compose the text blob that gets embedded for one movie.

    Optimized for semantic search: themes (keywords + genres) come first and
    are listed once more inside the narrative context, so "space, time
    travel, father-daughter" style signals dominate the embedding instead of
    overview prose. Overview is truncated to keep vectors comparable.
    """
    title = (movie.title or "Untitled").strip()
    year = f" ({movie.release_year})" if movie.release_year else ""

    genres = [str(g) for g in (movie.genres or []) if str(g).strip()]
    keywords = [str(k) for k in (movie.keywords or []) if str(k).strip()]

    # Themes = keywords + genres, deduplicated, order-preserving.
    themes: list[str] = []
    for item in (*keywords, *genres):
        if item not in themes:
            themes.append(item)

    overview = (movie.overview or "").strip()
    if len(overview) > _MAX_OVERVIEW_CHARS:
        overview = overview[:_MAX_OVERVIEW_CHARS].rsplit(" ", 1)[0] + "…"

    lines = [
        f"Title: {title}{year}",
        f"Genres: {', '.join(genres) if genres else 'unknown'}",
        f"Themes: {', '.join(themes) if themes else 'unknown'}",
        f"Overview: {overview if overview else 'no synopsis available'}",
    ]
    return "\n".join(lines)


class EmbeddingClient:
    """Client for any OpenAI-compatible ``POST /embeddings`` endpoint.

    Retries transient failures (429/5xx/connection errors) with exponential
    backoff honoring ``Retry-After``; raises ``EmbeddingError`` immediately
    for permanent 4xx responses.
    """

    def __init__(
        self,
        api_key: str,
        *,
        model: str,
        dimensions: int,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise EmbeddingError(
                "OPENAI_API_KEY is empty. Set it in backend/.env (or a "
                "compatible provider's key with OPENAI_BASE_URL)."
            )
        self._model = model
        self._dimensions = dimensions
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            headers={"Authorization": f"Bearer {api_key}"},
            transport=transport,
        )

    async def aclose(self) -> None:
        """Release the underlying HTTP connection pool."""
        await self._client.aclose()

    async def _post_with_retry(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST with rate-limit-aware exponential backoff."""
        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.post(OPENAI_EMBEDDINGS_PATH, json=payload)
            except httpx.HTTPError as exc:  # connection-level failure
                last_error = exc
                await _sleep_backoff(attempt)
                continue

            if response.status_code == httpx.codes.TOO_MANY_REQUESTS or (
                response.status_code >= 500
            ):
                last_error = EmbeddingError(
                    f"embeddings endpoint returned {response.status_code}"
                )
                await _sleep_backoff(
                    attempt, retry_after=response.headers.get("Retry-After")
                )
                continue

            if response.status_code >= 400:
                raise EmbeddingError(
                    f"embeddings endpoint returned {response.status_code}: "
                    f"{response.text[:200]}"
                )
            body: dict[str, Any] = response.json()
            return body

        raise EmbeddingError(
            f"Gave up on embeddings endpoint after {_MAX_RETRIES} attempts: {last_error}"
        )

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed texts, returning one vector per input (same order)."""
        if not texts:
            return []

        payload: dict[str, Any] = {"model": self._model, "input": texts}
        # Only OpenAI's text-embedding-3 family supports the `dimensions`
        # parameter; other compatible providers use their native size.
        if self._model.startswith("text-embedding-3"):
            payload["dimensions"] = self._dimensions

        body = await self._post_with_retry(payload)
        data = sorted(body.get("data", []), key=lambda item: item.get("index", 0))
        vectors = [list(map(float, item["embedding"])) for item in data]
        if len(vectors) != len(texts):
            raise EmbeddingError(
                f"embeddings endpoint returned {len(vectors)} vectors for "
                f"{len(texts)} inputs"
            )
        for vector in vectors:
            if len(vector) != self._dimensions:
                raise EmbeddingError(
                    f"embeddings endpoint returned {len(vector)} dims; expected "
                    f"{self._dimensions}. Keep EMBEDDING_DIMENSIONS and the "
                    "model's native size consistent."
                )
        return vectors


async def _sleep_backoff(attempt: int, retry_after: str | None = None) -> None:
    """Sleep exponentially longer per attempt, honoring Retry-After."""
    if retry_after is not None:
        try:
            await asyncio.sleep(max(0.0, float(retry_after)))
            return
        except ValueError:
            pass  # malformed header — fall back to exponential backoff
    await asyncio.sleep(_BACKOFF_BASE_SECONDS * (2**attempt) + random.uniform(0, 0.25))


def create_default_client() -> EmbeddingClient:
    """Build an EmbeddingClient from application settings (shared by services)."""
    settings = get_settings()
    return EmbeddingClient(
        api_key=settings.openai_api_key,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        base_url=settings.openai_base_url,
    )


def _require_matching_dimensions() -> None:
    """Fail fast if configured dims don't match the DB vector column."""
    settings = get_settings()
    if settings.embedding_dimensions != EMBEDDING_DIMENSIONS:
        raise EmbeddingError(
            f"EMBEDDING_DIMENSIONS={settings.embedding_dimensions} but the "
            f"movies.embedding column is vector({EMBEDDING_DIMENSIONS}). "
            "Keep them identical."
        )


async def embed_movie(
    movie: EmbeddableMovie, *, client: EmbeddingClient | None = None
) -> list[float]:
    """Embed a single movie; returns a 1536-dim vector."""
    owns_client = client is None
    if client is None:
        _require_matching_dimensions()
        client = create_default_client()
    try:
        vectors = await client.embed_batch([build_embedding_text(movie)])
    finally:
        if owns_client:
            await client.aclose()
    return vectors[0]


async def _fetch_missing_batch(
    session: AsyncSession, batch_size: int, exclude_ids: Sequence[Any]
) -> Sequence[Movie]:
    """Fetch up to ``batch_size`` movies whose embedding is still NULL.

    Ordered by id for a deterministic, resumable order; ``exclude_ids``
    skips movies that already failed during this run.
    """
    statement = select(Movie).where(Movie.embedding.is_(None))
    if exclude_ids:
        statement = statement.where(Movie.id.not_in(list(exclude_ids)))
    statement = statement.order_by(Movie.id).limit(batch_size)
    result = await session.scalars(statement)
    return list(result.all())


async def embed_all_missing_movies(
    batch_size: int = 100,
    *,
    limit: int | None = None,
    client: EmbeddingClient | None = None,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
) -> EmbeddingStats:
    """Embed every movie whose ``embedding`` is NULL, in resumable batches.

    Commits after each batch. A batch that permanently fails is logged, its
    movie ids are excluded for the rest of the run, and they are reported in
    the returned stats (they stay NULL and will be retried on the next run).
    """
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")

    _require_matching_dimensions()
    stats = EmbeddingStats()
    started = time.monotonic()
    owns_client = client is None
    if client is None:
        client = create_default_client()
    session_factory = sessionmaker or get_sessionmaker()
    exclude_ids: list[Any] = []

    try:
        while stats.embedded + stats.failed < (limit if limit is not None else 10**12):
            async with session_factory() as session:
                # Respect --limit exactly by shrinking the final batch.
                current_batch_size = (
                    batch_size
                    if limit is None
                    else min(batch_size, limit - stats.embedded - stats.failed)
                )
                movies = await _fetch_missing_batch(session, current_batch_size, exclude_ids)
                if not movies:
                    break

                try:
                    texts = [build_embedding_text(movie) for movie in movies]
                    vectors = await client.embed_batch(texts)
                except EmbeddingError as exc:
                    # Whole batch failed permanently — skip these ids and go on.
                    failed = [movie.id for movie in movies]
                    stats.failed += len(failed)
                    stats.failed_ids.extend(failed)
                    exclude_ids.extend(failed)
                    logger.warning(
                        "Batch failed (%d movies), skipping them this run: %s",
                        len(failed),
                        exc,
                    )
                    continue

                # Write vectors back through pgvector's type handlers.
                for movie, vector in zip(movies, vectors, strict=True):
                    movie.embedding = vector
                await session.commit()

                stats.embedded += len(movies)
                logger.info(
                    "%d movies embedded (batch of %d, %d failed so far)",
                    stats.embedded,
                    len(movies),
                    stats.failed,
                )
    finally:
        if owns_client:
            await client.aclose()

    async with session_factory() as session:
        remaining_result = await session.scalars(
            select(Movie.id).where(Movie.embedding.is_(None))
        )
        stats.remaining = len(set(remaining_result.all()))

    stats.duration_seconds = time.monotonic() - started
    return stats


def _parse_args(argv: Iterable[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.services.embeddings",
        description="Generate semantic embeddings for movies in Postgres.",
    )
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Embed every movie whose embedding IS NULL, in batches of 100.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Movies per embeddings request; default: 100",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Embed at most N movies this run (useful for smoke tests).",
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
    import sys

    args = _parse_args(argv)
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    if not args.backfill:
        print("Nothing to do: pass --backfill (see --help).", file=sys.stderr)
        return 2
    stats = asyncio.run(
        embed_all_missing_movies(batch_size=args.batch_size, limit=args.limit)
    )
    logger.info(
        "Done: %d embedded, %d failed, %d still missing, in %.1fs",
        stats.embedded,
        stats.failed,
        stats.remaining,
        stats.duration_seconds,
    )
    return 0 if stats.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
