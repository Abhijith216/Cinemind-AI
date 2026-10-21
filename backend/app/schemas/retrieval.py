"""Pydantic schemas for the hybrid search endpoint.

Every component score is broken out in the response so the product weights
(0.45 / 0.20 / 0.15 / 0.10 / 0.10) can be debugged directly from the API.
"""

import uuid

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.common import MovieOut, MoviePersonalityOut


class SearchFilters(BaseModel):
    """Hard filters applied at the SQL candidate stage."""

    genres: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    excluded_genres: list[str] = Field(default_factory=list, max_length=20)
    excluded_themes: list[str] = Field(default_factory=list, max_length=20)
    min_rating: float | None = Field(default=None, ge=0, le=10)
    min_release_year: int | None = Field(default=None, ge=1888)
    max_release_year: int | None = Field(default=None, ge=1888)
    max_runtime: int | None = Field(default=None, ge=1, le=1000)

    @model_validator(mode="after")
    def validate_year_range(self) -> "SearchFilters":
        if (
            self.min_release_year is not None
            and self.max_release_year is not None
            and self.min_release_year > self.max_release_year
        ):
            raise ValueError("Minimum year must not exceed maximum year")
        return self


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

    @field_validator("query")
    @classmethod
    def trim_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Describe a movie, genre or theme to search for")
        return value


class DiscoverMovieOut(BaseModel):
    movie: MovieOut
    explanation: str
    matched_terms: list[str]


class DiscoverResponse(BaseModel):
    query: str
    results: list[DiscoverMovieOut]
    search_mode: str = "catalog"
    notice: str = "Searches titles, genres, themes and plot summaries in the saved movie catalog."


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
