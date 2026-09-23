"""Module 7 — Movie personality vectors (nine 0-100 trait scores).

``analyze_personality`` calls the LLM once per movie with a calibration
prompt over the movie's dossier (overview + genres + keywords). The model
returns ONLY a JSON object with the nine trait keys; any reasoning stays
inside the model and is never part of the reply — the response is validated
against ``MoviePersonalityOut`` (each trait an int 0-100), which doubles as
the anti-hallucination boundary for out-of-range values.

CLI usage (from ``backend/``):

    python -m app.services.personality --backfill

Resumability (same design as the embeddings backfill): batches of movies
with ``personality IS NULL`` are processed in a stable id order with a
commit after every batch — a crash loses at most one batch, and re-running
continues where it left off. Movies whose LLM call permanently fails are
excluded for the rest of the run, reported in the stats, and stay NULL for
the next run.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.db import get_sessionmaker
from app.models import Movie
from app.schemas.common import MoviePersonalityOut
from app.services.llm_client import ChatLLMClient, LLMError, create_chat_client

logger = logging.getLogger("app.personality")

_MAX_OVERVIEW_CHARS = 1500

PERSONALITY_SYSTEM_PROMPT = """You score movies on nine personality traits.
You will receive a movie dossier (title, year, genres, keywords, overview).

Score each trait 0-100 based ONLY on the dossier:
- emotion: depth and intensity of feeling the film evokes.
- mind_blowing: twist density, conceptual audacity, how much it scrambles
  expectations.
- darkness: grimness and moral bleakness of tone (not gore).
- humor: how funny it is.
- violence: intensity of on-screen violence.
- romance: prominence of a romantic storyline.
- hopefulness: optimistic vs bleak outlook and ending.
- plot_complexity: narrative intricacy, nonlinearity, layered reveals.
- rewatchability: replay value.

Calibration: 0 = absent, 25 = slight, 50 = present but not defining,
75 = strong, 100 = defining/extreme. Use the whole 0-100 range; reserve
90+ for traits that define the film.

Reason silently. Your reply must be ONLY a JSON object with exactly these
nine keys — emotion, mind_blowing, darkness, humor, violence, romance,
hopefulness, plot_complexity, rewatchability — each an integer 0-100.
No extra keys, no commentary, no markdown."""


class PersonalityError(RuntimeError):
    """Raised when the LLM cannot produce a valid personality vector."""


@dataclass
class PersonalityStats:
    """Result summary for one backfill run."""

    scored: int = 0
    failed: int = 0
    remaining: int = 0
    duration_seconds: float = 0.0
    failed_ids: list[Any] = field(default_factory=list)


class PersonalityMovie(Protocol):
    """Structural type: the subset of Movie fields scoring uses."""

    @property
    def id(self) -> Any: ...
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


def build_personality_dossier(movie: PersonalityMovie) -> str:
    """Compact dossier the LLM scores: title/year, genres, keywords, overview."""
    title = (movie.title or "Untitled").strip()
    year = f" ({movie.release_year})" if movie.release_year else ""

    genres = [str(genre) for genre in (movie.genres or []) if str(genre).strip()]
    keywords = [str(keyword) for keyword in (movie.keywords or []) if str(keyword).strip()]

    overview = (movie.overview or "").strip()
    if len(overview) > _MAX_OVERVIEW_CHARS:
        overview = overview[:_MAX_OVERVIEW_CHARS].rsplit(" ", 1)[0] + "…"

    lines = [
        f"Title: {title}{year}",
        f"Genres: {', '.join(genres) if genres else 'unknown'}",
        f"Keywords: {', '.join(keywords) if keywords else 'unknown'}",
        f"Overview: {overview if overview else 'no synopsis available'}",
    ]
    return "\n".join(lines)


async def analyze_personality(
    movie: PersonalityMovie, *, client: ChatLLMClient | None = None
) -> dict[str, int]:
    """Score one movie on the nine traits; returns ``{trait: 0-100 int}``.

    One LLM call per movie (two only if the self-repair round-trip fires).
    The reply is validated against ``MoviePersonalityOut`` — out-of-range
    or missing values raise ``PersonalityError`` rather than reaching the
    database.
    """
    owns_client = client is None
    if client is None:
        client = create_chat_client()
    try:
        result = await client.complete_json(
            system_prompt=PERSONALITY_SYSTEM_PROMPT,
            user_prompt=build_personality_dossier(movie),
            schema_model=MoviePersonalityOut,
        )
    except LLMError as exc:
        raise PersonalityError(f"personality scoring failed: {exc}") from exc
    finally:
        if owns_client:
            await client.aclose()
    vector: dict[str, int] = result.model_dump()
    return vector


# ---------------------------------------------------------------------------
# Resumable backfill — same shape as embeddings.embed_all_missing_movies.
# ---------------------------------------------------------------------------

AnalyzeMovieFn = Callable[[Any], Awaitable[dict[str, int]]]


def _default_analyzer(client: ChatLLMClient) -> AnalyzeMovieFn:
    """Bind one shared client so batches don't rebuild HTTP pools."""

    async def _analyze(movie: Any) -> dict[str, int]:
        return await analyze_personality(movie, client=client)

    return _analyze


async def _fetch_missing_batch(
    session: AsyncSession, batch_size: int, exclude_ids: Sequence[Any]
) -> Sequence[Movie]:
    """Up to ``batch_size`` movies with NULL personality, stable id order."""
    statement = select(Movie).where(Movie.personality.is_(None))
    if exclude_ids:
        statement = statement.where(Movie.id.not_in(list(exclude_ids)))
    statement = statement.order_by(Movie.id).limit(batch_size)
    result = await session.scalars(statement)
    return list(result.all())


async def backfill_personality(
    batch_size: int = 20,
    *,
    limit: int | None = None,
    analyzer: AnalyzeMovieFn | None = None,
    client: ChatLLMClient | None = None,
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
) -> PersonalityStats:
    """Score every movie whose ``personality`` is NULL, in resumable batches.

    The LLM is called once per movie; a single movie's failure is isolated
    (the rest of its batch still scores). Commits after each batch; failed
    movies stay NULL and are retried on the next run.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")

    stats = PersonalityStats()
    started = time.monotonic()
    owns_client = analyzer is None and client is None
    if analyzer is None:
        if client is None:
            client = create_chat_client()
        analyzer = _default_analyzer(client)
    session_factory = sessionmaker or get_sessionmaker()
    exclude_ids: list[Any] = []

    try:
        while stats.scored + stats.failed < (limit if limit is not None else 10**12):
            async with session_factory() as session:
                current_batch_size = (
                    batch_size
                    if limit is None
                    else min(batch_size, limit - stats.scored - stats.failed)
                )
                movies = await _fetch_missing_batch(
                    session, current_batch_size, exclude_ids
                )
                if not movies:
                    break

                scored_any = False
                for movie in movies:
                    try:
                        vector = await analyzer(movie)
                        # Defensive re-validation at the DB boundary.
                        validated = MoviePersonalityOut.model_validate(vector)
                        movie.personality = validated.model_dump()
                        stats.scored += 1
                        scored_any = True
                    except (PersonalityError, ValueError) as exc:
                        stats.failed += 1
                        stats.failed_ids.append(movie.id)
                        exclude_ids.append(movie.id)
                        logger.warning(
                            "Personality scoring failed for movie id=%s, "
                            "skipping this run: %s",
                            movie.id,
                            exc,
                        )
                if scored_any:
                    await session.commit()
                logger.info(
                    "%d movies scored (%d failed so far) after batch of %d",
                    stats.scored,
                    stats.failed,
                    len(movies),
                )
    finally:
        if owns_client and client is not None:
            await client.aclose()

    async with session_factory() as session:
        remaining_result = await session.scalars(
            select(Movie.id).where(Movie.personality.is_(None))
        )
        stats.remaining = len(set(remaining_result.all()))

    stats.duration_seconds = time.monotonic() - started
    return stats


def _parse_args(argv: Iterable[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.services.personality",
        description="Score movies' nine personality traits via the LLM.",
    )
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Score every movie whose personality IS NULL.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=20,
        help="Movies per DB commit (one LLM call each); default: 20",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Score at most N movies this run (useful for smoke tests).",
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
        backfill_personality(batch_size=args.batch_size, limit=args.limit)
    )
    logger.info(
        "Done: %d scored, %d failed, %d still missing, in %.1fs",
        stats.scored,
        stats.failed,
        stats.remaining,
        stats.duration_seconds,
    )
    return 0 if stats.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
