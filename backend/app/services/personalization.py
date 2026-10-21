"""Shared, bounded metadata affinity from the authenticated user's saved ratings."""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import case, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Movie, Rating
from app.schemas.explanation import LovedMovie, MatchedAttributes, UserTasteContext
from app.services.taste_profile import DISLIKED_THRESHOLD, LIKED_THRESHOLD

MAX_HISTORY = 500
MAX_KEYWORDS = 80


def rating_signal(score: int) -> float:
    if score >= LIKED_THRESHOLD:
        return (score - 6) / 4
    if score <= DISLIKED_THRESHOLD:
        return (score - 5) / 4
    return 0.0


@dataclass
class TasteSignals:
    genres: dict[str, float] = field(default_factory=dict)
    keywords: dict[str, float] = field(default_factory=dict)
    context: UserTasteContext = field(default_factory=UserTasteContext)

    def affinity(self, movie: Movie) -> float:
        """[-1, 1] metadata affinity, not a probability or content-safety score."""
        genres = {str(tag).casefold() for tag in movie.genres or []}
        keywords = {str(tag).casefold() for tag in movie.keywords or []}
        genre_weights = {tag.casefold(): weight for tag, weight in self.genres.items()}
        keyword_weights = {tag.casefold(): weight for tag, weight in self.keywords.items()}
        genre_score = sum(genre_weights.get(tag, 0) for tag in genres) / max(1, len(genres))
        theme_score = sum(keyword_weights.get(tag, 0) for tag in keywords) / 3
        return 0.65 * genre_score + 0.35 * max(-1, min(1, theme_score))

    def sql_affinity(self) -> Any:
        """Equivalent score for the canonical genre/keyword arrays stored by TMDb."""
        genres: Any = literal(0.0)
        keywords: Any = literal(0.0)
        for tag, weight in self.genres.items():
            genres = genres + case((Movie.genres.contains([tag]), weight), else_=0.0)
        for tag, weight in self.keywords.items():
            keywords = keywords + case((Movie.keywords.contains([tag]), weight), else_=0.0)
        return 0.65 * genres / func.greatest(
            1, func.jsonb_array_length(Movie.genres)
        ) + 0.35 * func.greatest(-1.0, func.least(1.0, keywords / 3.0))


def signals_from_ratings(rows: list[tuple[Movie, int]]) -> TasteSignals:
    """Conflicting scores cancel per tag; neutral ratings contribute no preference."""
    buckets: list[dict[str, list[float]]] = [defaultdict(list), defaultdict(list)]
    labels: list[dict[str, str]] = [{}, {}]
    for movie, score in rows:
        strength = rating_signal(score)
        if not strength:
            continue
        for index, tags in enumerate((movie.genres or [], movie.keywords or [])):
            for tag in dict.fromkeys(str(value).strip() for value in tags):
                key = tag.casefold()
                if key:
                    labels[index].setdefault(key, tag)
                    buckets[index][key].append(strength)
    weights = []
    for index, bucket in enumerate(buckets):
        ranked = sorted(
            ((key, sum(values) / len(values)) for key, values in bucket.items()),
            key=lambda item: (-abs(item[1]), item[0]),
        )
        weights.append({labels[index][key]: weight for key, weight in ranked if weight})
    loved = sorted(
        ((movie, score) for movie, score in rows if score >= LIKED_THRESHOLD),
        key=lambda item: -item[1],  # stable: input is most recent first
    )[:5]
    return TasteSignals(
        genres=weights[0],
        keywords=dict(list(weights[1].items())[:MAX_KEYWORDS]),
        context=UserTasteContext(
            loved_movies=[
                LovedMovie(
                    title=movie.title,
                    score=score,
                    genres=movie.genres or [],
                    keywords=movie.keywords or [],
                    personality=movie.personality,
                )
                for movie, score in loved
            ]
        ),
    )


async def load_taste_signals(session: AsyncSession, user_id: UUID | None) -> TasteSignals:
    if user_id is None:
        return TasteSignals()
    rows = (
        await session.execute(
            select(Movie, Rating.score)
            .join(Rating, Rating.movie_id == Movie.id)
            .where(Rating.user_id == user_id)
            .order_by(Rating.rated_at.desc(), Rating.id)
            .limit(MAX_HISTORY)
        )
    ).all()
    return signals_from_ratings([(movie, score) for movie, score in rows])


def unrated_by(user_id: UUID) -> Any:
    # Exclude the user's entire rated history, not just the bounded scoring window.
    return Movie.id.not_in(select(Rating.movie_id).where(Rating.user_id == user_id))


def taste_matches(movie: Movie, signals: TasteSignals) -> MatchedAttributes:
    from app.services.explain import compute_matched_attributes

    matches = compute_matched_attributes(movie, None, signals.context)
    positive_genres = {tag.casefold() for tag, weight in signals.genres.items() if weight > 0}
    positive_themes = {tag.casefold() for tag, weight in signals.keywords.items() if weight > 0}
    matches.genres = [
        str(tag) for tag in movie.genres or [] if str(tag).casefold() in positive_genres
    ]
    matches.themes = [
        str(tag) for tag in movie.keywords or [] if str(tag).casefold() in positive_themes
    ]
    return matches
