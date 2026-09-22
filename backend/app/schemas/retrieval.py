"""Pydantic schemas for the hybrid search endpoint.

Every component score is broken out in the response so the product weights
(0.45 / 0.20 / 0.15 / 0.10 / 0.10) can be debugged directly from the API.
"""

import uuid

from pydantic import BaseModel, Field

from app.schemas.common import MovieOut, MoviePersonalityOut


class SearchFilters(BaseModel):
    """Hard filters applied at the SQL candidate stage."""

    genres: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    min_rating: float | None = Field(default=None, ge=0, le=10)
    min_release_year: int | None = Field(default=None, ge=1888)
    max_release_year: int | None = Field(default=None, ge=1888)


class SearchRequest(BaseModel):
    """Request body for POST /search/hybrid."""

    query: str = Field(
        min_length=1,
        max_length=1000,
        examples=["emotional mind-blowing sci-fi movie"],
    )
    filters: SearchFilters = Field(default_factory=SearchFilters)
    user_id: uuid.UUID | None = None
    limit: int = Field(default=20, ge=1, le=50)


class ComponentScores(BaseModel):
    """The five hybrid-scoring components for one movie."""

    semantic_similarity: float
    user_history_match: float
    genre_similarity: float
    normalized_rating: float
    normalized_popularity: float


class RankedMovieOut(BaseModel):
    """One ranked result: movie + final score + component breakdown."""

    movie: MovieOut
    final_score: float
    components: ComponentScores


class SearchResponse(BaseModel):
    """Response for POST /search/hybrid."""

    query: str
    results: list[RankedMovieOut]
    applied_weights: dict[str, float]


__all__ = [
    "ComponentScores",
    "MoviePersonalityOut",
    "RankedMovieOut",
    "SearchFilters",
    "SearchRequest",
    "SearchResponse",
]
