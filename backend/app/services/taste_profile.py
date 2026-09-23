"""Module 6 — User taste profile.

Updates the per-user taste profile after every rating and produces the
monthly snapshots that feed the Phase 14 taste-evolution chart.

Bounded-recency merge (the "light decay/dedup"): every list is
deduplicated case-insensitively, newly-touched items move to the front
(recency), and the list is capped at ``MAX_PROFILE_ITEMS``. Old taste
naturally drops off the end as new ratings arrive — no unbounded growth,
and recent taste is never shadowed by stale entries.

Update policy (agreed thresholds):
- ``score >= 7``  → merge the movie's genres/keywords into ``likes`` and
  its keyword themes into ``favorite_themes``.
- ``score <= 4``  → merge into ``dislikes``.
- ``5 <= score <= 6`` → rating is stored, profile is left unchanged.

The snapshot job ranks a month's ratings by exposure weighted with score
(see ``compute_dominant``) and upserts one ``taste_snapshots`` row per
(user, month). It is a plain function today; cron can call the CLI later.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import logging
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Movie, Rating, TasteSnapshot, UserTasteProfile
from app.schemas.taste import TasteProfileOut

logger = logging.getLogger("app.taste_profile")

LIKED_THRESHOLD = 7
DISLIKED_THRESHOLD = 4

# Profile lists are capped; combined with recency ordering this is the
# decay: every merge pushes older entries one step toward the cut-off.
MAX_PROFILE_ITEMS = 50

# Snapshot ranking bounds.
MAX_DOMINANT_ITEMS = 5


def merge_tags(existing: Sequence[str], additions: Sequence[str]) -> list[str]:
    """Merge ``additions`` into ``existing``: dedup (case-insensitive),
    newest first, capped at ``MAX_PROFILE_ITEMS``.

    Pure function — the same shape the tests exercise offline.
    """
    merged: list[str] = []
    seen: set[str] = set()

    def push(value: str) -> None:
        key = value.strip().lower()
        if not key or key in seen:
            return
        seen.add(key)
        merged.append(value.strip())

    for value in additions:
        push(value)
    for value in existing:
        push(value)
    return merged[:MAX_PROFILE_ITEMS]


@dataclass
class TasteUpdateResult:
    """Outcome of one ``update_taste_profile`` call."""

    action: str  # "liked" | "disliked" | "neutral"
    likes: list[str] = field(default_factory=list)
    dislikes: list[str] = field(default_factory=list)
    favorite_themes: list[str] = field(default_factory=list)


def _string_list(values: Iterable[Any]) -> list[str]:
    return [str(value) for value in values if str(value).strip()]


async def update_taste_profile(
    session: AsyncSession, user_id: uuid.UUID, movie: Movie, score: int
) -> TasteUpdateResult:
    """Apply one rating's taste signal to the user's profile row.

    Loads (or lazily creates) the 1:1 ``UserTasteProfile``, merges the
    movie's real attributes per the threshold policy, and commits. Safe to
    call inside the /ratings request transaction — the extra commit is a
    no-op there.
    """
    profile = await session.get(UserTasteProfile, user_id)
    if profile is None:
        profile = UserTasteProfile(user_id=user_id, likes=[], dislikes=[], favorite_themes=[])
        session.add(profile)

    genres = _string_list(movie.genres or [])
    keywords = _string_list(movie.keywords or [])

    if score >= LIKED_THRESHOLD:
        action = "liked"
        profile.likes = merge_tags(list(profile.likes), [*genres, *keywords])
        profile.favorite_themes = merge_tags(list(profile.favorite_themes), keywords)
    elif score <= DISLIKED_THRESHOLD:
        action = "disliked"
        profile.dislikes = merge_tags(list(profile.dislikes), [*genres, *keywords])
    else:
        action = "neutral"

    await session.commit()
    logger.info(
        "Taste profile %s for user %s (%d likes / %d dislikes / %d themes)",
        action,
        user_id,
        len(profile.likes),
        len(profile.dislikes),
        len(profile.favorite_themes),
    )
    return TasteUpdateResult(
        action=action,
        likes=list(profile.likes),
        dislikes=list(profile.dislikes),
        favorite_themes=list(profile.favorite_themes),
    )


async def get_taste_profile(
    session: AsyncSession, user_id: uuid.UUID
) -> TasteProfileOut | None:
    """Return the user's current profile, or None if they never rated."""
    profile = await session.get(UserTasteProfile, user_id)
    if profile is None:
        return None
    return TasteProfileOut(
        user_id=user_id,
        likes=_string_list(profile.likes),
        dislikes=_string_list(profile.dislikes),
        favorite_themes=_string_list(profile.favorite_themes),
        updated_at=profile.updated_at,
    )


# ---------------------------------------------------------------------------
# Monthly snapshot job (feeds the Phase 14 taste-evolution chart).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MonthRating:
    """One (movie, score) pair within the snapshot month."""

    genres: list[str]
    keywords: list[str]
    score: int


def month_window(month: str) -> tuple[datetime.datetime, datetime.datetime]:
    """``"2026-09"`` → aware UTC [first day, first day of next month)."""
    year_text, _, month_text = month.partition("-")
    year, month_number = int(year_text), int(month_text)
    start = datetime.datetime(year, month_number, 1, tzinfo=datetime.UTC)
    if month_number == 12:
        end = datetime.datetime(year + 1, 1, 1, tzinfo=datetime.UTC)
    else:
        end = datetime.datetime(year, month_number + 1, 1, tzinfo=datetime.UTC)
    return start, end


def compute_dominant(
    ratings: Sequence[MonthRating],
) -> tuple[list[str], list[str]]:
    """Rank the month's genres/themes by exposure weighted with score.

    Weight = Σ score over ratings touching the tag, so a movie you rated 10
    contributes five times a 2. Ties break by count, then alphabetically,
    so the chart is stable across runs. All scores count — the chart is
    about exposure, not just love.
    """
    genre_weight: dict[str, tuple[int, int]] = {}
    theme_weight: dict[str, tuple[int, int]] = {}
    for rating in ratings:
        for genre in rating.genres:
            weight, count = genre_weight.get(genre.lower(), (0, 0))
            genre_weight[genre.lower()] = (weight + rating.score, count + 1)
        for keyword in rating.keywords:
            weight, count = theme_weight.get(keyword.lower(), (0, 0))
            theme_weight[keyword.lower()] = (weight + rating.score, count + 1)

    def ranked(weights: dict[str, tuple[int, int]]) -> list[str]:
        ordered = sorted(
            weights.items(), key=lambda item: (-item[1][0], -item[1][1], item[0])
        )
        return [tag for tag, _ in ordered[:MAX_DOMINANT_ITEMS]]

    return ranked(genre_weight), ranked(theme_weight)


async def _load_month_ratings(
    session: AsyncSession,
    user_id: uuid.UUID,
    start: datetime.datetime,
    end: datetime.datetime,
) -> list[MonthRating]:
    statement = (
        select(Movie.genres, Movie.keywords, Rating.score)
        .join(Rating, Rating.movie_id == Movie.id)
        .where(
            Rating.user_id == user_id,
            Rating.rated_at >= start,
            Rating.rated_at < end,
        )
        .order_by(Rating.rated_at)
    )
    rows = (await session.execute(statement)).all()
    return [
        MonthRating(
            genres=_string_list(genres or []),
            keywords=_string_list(keywords or []),
            score=int(score),
        )
        for genres, keywords, score in rows
    ]


async def snapshot_monthly(
    session: AsyncSession,
    user_id: uuid.UUID,
    month: str | None = None,
) -> TasteSnapshot | None:
    """Summarize the user's dominant genres/themes for one month.

    Upserts the ``taste_snapshots`` row (one per user+month) and commits.
    Returns None when the user has no ratings that month (no empty rows —
    the chart skips silent months). ``month`` defaults to the current UTC
    month; pass ``"2026-08"`` to rebuild a past month.
    """
    if month is None:
        month = datetime.datetime.now(datetime.UTC).strftime("%Y-%m")
    start, end = month_window(month)

    month_ratings = await _load_month_ratings(session, user_id, start, end)
    if not month_ratings:
        logger.info("No ratings for user %s in %s; no snapshot written", user_id, month)
        return None

    dominant_genres, dominant_themes = compute_dominant(month_ratings)

    snapshot = await session.execute(
        select(TasteSnapshot).where(
            TasteSnapshot.user_id == user_id, TasteSnapshot.month == month
        )
    )
    row = snapshot.scalar_one_or_none()
    if row is None:
        row = TasteSnapshot(user_id=user_id, month=month)
        session.add(row)
    row.dominant_genres = dominant_genres
    row.dominant_themes = dominant_themes

    await session.commit()
    logger.info(
        "Snapshot %s for user %s: genres=%s themes=%s",
        month,
        user_id,
        dominant_genres,
        dominant_themes,
    )
    return row


# ---------------------------------------------------------------------------
# CLI — call manually today, cron later.
# ---------------------------------------------------------------------------


def _parse_args(argv: Iterable[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.services.taste_profile",
        description="Rebuild monthly taste snapshots for the evolution chart.",
    )
    parser.add_argument(
        "--user-id",
        required=True,
        help="UUID of the user to snapshot",
    )
    parser.add_argument(
        "--month",
        default=None,
        help='Month as "YYYY-MM" (default: the current month)',
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log verbosity; default: INFO",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


async def _run(args: argparse.Namespace) -> int:
    from app.core.db import get_sessionmaker

    session_factory = get_sessionmaker()
    async with session_factory() as session:
        snapshot = await snapshot_monthly(
            session, uuid.UUID(args.user_id), month=args.month
        )
    if snapshot is None:
        print(f"No ratings found for {args.month or 'the current month'} — nothing written.")
        return 1
    print(f"Snapshot {snapshot.month} written: genres={snapshot.dominant_genres} "
          f"themes={snapshot.dominant_themes}")
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    """CLI entrypoint. Returns a process exit code."""
    args = _parse_args(argv)
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
