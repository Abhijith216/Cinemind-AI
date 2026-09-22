"""Module 3 — Hybrid retrieval.

Two-stage ranking that keeps the heavy work in Postgres:

1. **Candidate generation (SQL):** cosine similarity between the query
   embedding and ``movies.embedding`` is computed by pgvector (``<=>``
   cosine distance) and the top ~200 candidates are fetched in one query.
2. **Re-ranking (Python):** the full product-spec formula over the
   candidate set, with every component broken out for explainability:

       final_score = 0.45 * semantic_similarity
                   + 0.20 * user_history_match
                   + 0.15 * genre_similarity
                   + 0.10 * normalized_rating
                   + 0.10 * normalized_popularity

Component definitions:
- ``semantic_similarity`` — ``1 - (query <=> embedding)``, computed in SQL
  (the HNSW index accelerates the ordering).
- ``genre_similarity`` — Jaccard similarity between the query's genres and
  each movie's genres (|intersection| / |union|); 0 when the query has none.
- ``user_history_match`` — cosine similarity between the movie's
  ``personality`` vector (9 traits, 0-100) and the average personality
  vector of the user's loved (>= 8) ratings; 0.0 without such history.
  Personality vectors are non-negative, so their cosine is already [0, 1].
- ``normalized_rating`` / ``normalized_popularity`` — min-max normalized
  within the current candidate set (guards against division by zero).
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EMBEDDING_DIMENSIONS, Movie, Rating
from app.schemas.retrieval import SearchFilters

logger = logging.getLogger("app.retrieval")

# Product-spec weights (explicit, debuggable — see /search/hybrid response).
WEIGHT_SEMANTIC = 0.45
WEIGHT_HISTORY = 0.20
WEIGHT_GENRE = 0.15
WEIGHT_RATING = 0.10
WEIGHT_POPULARITY = 0.10

# Stage 1: how many candidates the SQL cosine search fetches before re-rank.
CANDIDATE_LIMIT = 200

# Ratings at or above this count as "loved" for the user-history component.
LOVED_THRESHOLD = 8.0

_TRAITS: tuple[str, ...] = (
    "emotion",
    "mind_blowing",
    "darkness",
    "humor",
    "violence",
    "romance",
    "hopefulness",
    "plot_complexity",
    "rewatchability",
)


@dataclass
class RankedMovie:
    """One re-ranked result with every component score broken out."""

    movie: Movie
    final_score: float
    semantic_similarity: float
    user_history_match: float
    genre_similarity: float
    normalized_rating: float
    normalized_popularity: float
    explanation_notes: list[str] = field(default_factory=list)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def jaccard_similarity(query_genres: Iterable[str], movie_genres: Iterable[Any] | None) -> float:
    """Jaccard similarity |A∩B| / |A∪B| between two genre sets."""
    query_set = {str(genre).strip().lower() for genre in query_genres if str(genre).strip()}
    movie_set = {str(genre).strip().lower() for genre in movie_genres or [] if str(genre).strip()}
    if not query_set or not movie_set:
        return 0.0
    union = query_set | movie_set
    return len(query_set & movie_set) / len(union)


def _personality_vector(personality: Any) -> list[float] | None:
    """Extract the 9-trait personality vector from a JSONB value."""
    if not isinstance(personality, dict):
        return None
    values: list[float] = []
    for trait in _TRAITS:
        raw = personality.get(trait)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return None
        values.append(float(raw))
    return values


def cosine_similarity(a: Iterable[float], b: Iterable[float]) -> float:
    """Plain cosine similarity between two equal-length vectors."""
    vector_a = list(a)
    vector_b = list(b)
    if not vector_a or len(vector_a) != len(vector_b):
        return 0.0
    dot = sum(x * y for x, y in zip(vector_a, vector_b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in vector_a))
    norm_b = math.sqrt(sum(y * y for y in vector_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def min_max_normalize(values: list[float]) -> list[float]:
    """Min-max scale values into [0, 1]; all-equal lists map to 0.5."""
    if not values:
        return []
    low, high = min(values), max(values)
    if high - low < 1e-12:
        return [0.5] * len(values)
    return [(value - low) / (high - low) for value in values]


async def fetch_user_history_vector(
    session: AsyncSession, user_id: UUID | None
) -> list[float] | None:
    """Average personality vector across the user's loved (>= 8) movies.

    Returns None when the user is anonymous or has no qualifying ratings.
    """
    if user_id is None:
        return None

    statement = (
        select(Movie.personality)
        .join(Rating, Rating.movie_id == Movie.id)
        .where(Rating.user_id == user_id, Rating.score >= LOVED_THRESHOLD)
    )
    rows = (await session.execute(statement)).scalars().all()

    vectors = [
        vector
        for row in rows
        if (vector := _personality_vector(row)) is not None
    ]
    if not vectors:
        return None

    average = [0.0] * len(_TRAITS)
    for vector in vectors:
        for index, value in enumerate(vector):
            average[index] += value
    return [value / len(vectors) for value in average]


def _candidate_statement(
    query_embedding: list[float], filters: SearchFilters
) -> Select[Any]:
    """Stage-1 SQL: cosine similarity in Postgres, top CANDIDATE_LIMIT rows."""
    statement = (
        select(
            Movie,
            (1 - Movie.embedding.cosine_distance(query_embedding)).label(
                "semantic_similarity"
            ),
        )
        .where(Movie.embedding.is_not(None))
        .order_by(Movie.embedding.cosine_distance(query_embedding))
        .limit(CANDIDATE_LIMIT)
    )
    if filters.min_rating is not None:
        statement = statement.where(Movie.vote_average >= filters.min_rating)
    if filters.min_release_year is not None:
        statement = statement.where(Movie.release_year >= filters.min_release_year)
    if filters.max_release_year is not None:
        statement = statement.where(Movie.release_year <= filters.max_release_year)
    if filters.genres:
        # Movie must have at least ONE of the requested genres (any-of).
        statement = statement.where(
            or_(*(Movie.genres.contains([genre]) for genre in filters.genres))
        )
    if filters.languages:
        statement = statement.where(Movie.language.in_(filters.languages))
    return statement


def re_rank(
    candidates: list[tuple[Movie, float]],
    *,
    query_genres: list[str],
    history_vector: list[float] | None,
) -> list[RankedMovie]:
    """Stage-2: apply the full weighted formula to the SQL candidate set."""
    if not candidates:
        return []

    rating_scores = min_max_normalize(
        [
            float(movie.vote_average) if movie.vote_average is not None else 0.0
            for movie, _ in candidates
        ]
    )
    popularity_scores = min_max_normalize(
        [
            float(movie.popularity) if movie.popularity is not None else 0.0
            for movie, _ in candidates
        ]
    )

    ranked: list[RankedMovie] = []
    for (movie, semantic), rating_norm, popularity_norm in zip(
        candidates, rating_scores, popularity_scores, strict=True
    ):
        semantic_clamped = _clamp01(max(0.0, float(semantic)))
        genre_similarity = jaccard_similarity(query_genres, movie.genres)

        history_match = 0.0
        if history_vector is not None:
            personality = _personality_vector(movie.personality)
            if personality is not None:
                # Non-negative trait vectors → cosine already in [0, 1].
                history_match = _clamp01(cosine_similarity(history_vector, personality))

        final_score = (
            WEIGHT_SEMANTIC * semantic_clamped
            + WEIGHT_HISTORY * history_match
            + WEIGHT_GENRE * genre_similarity
            + WEIGHT_RATING * rating_norm
            + WEIGHT_POPULARITY * popularity_norm
        )
        ranked.append(
            RankedMovie(
                movie=movie,
                final_score=final_score,
                semantic_similarity=semantic_clamped,
                user_history_match=history_match,
                genre_similarity=genre_similarity,
                normalized_rating=rating_norm,
                normalized_popularity=popularity_norm,
            )
        )

    ranked.sort(key=lambda item: item.final_score, reverse=True)
    return ranked


async def hybrid_search(
    session: AsyncSession,
    query_embedding: list[float],
    filters: SearchFilters,
    user_id: UUID | None,
    limit: int = 20,
) -> list[RankedMovie]:
    """Full pipeline: SQL candidates → weighted re-rank → top ``limit``."""
    if len(query_embedding) != EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"query embedding has {len(query_embedding)} dims; expected "
            f"{EMBEDDING_DIMENSIONS}"
        )

    history_vector = await fetch_user_history_vector(session, user_id)
    result = await session.execute(_candidate_statement(query_embedding, filters))
    candidates: list[tuple[Movie, float]] = [
        (movie, float(semantic)) for movie, semantic in result.all()
    ]
    logger.info(
        "Candidate stage returned %d movies (history: %s)",
        len(candidates),
        "yes" if history_vector is not None else "none",
    )

    ranked = re_rank(
        candidates,
        query_genres=filters.genres,
        history_vector=history_vector,
    )
    return ranked[:limit]


async def embed_query(text: str) -> list[float]:
    """Embed a free-text query with the configured embedding model."""
    from app.services.embeddings import create_default_client

    client = create_default_client()
    try:
        vectors = await client.embed_batch([text])
    finally:
        await client.aclose()
    return vectors[0]
