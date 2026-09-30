"""Movie + user Pydantic schemas (shared request/response contracts)."""

import uuid

from pydantic import BaseModel, ConfigDict, Field


class MoviePersonalityOut(BaseModel):
    """The nine 0-100 personality trait scores stored as JSONB on movies."""

    emotion: int = Field(ge=0, le=100)
    mind_blowing: int = Field(ge=0, le=100)
    darkness: int = Field(ge=0, le=100)
    humor: int = Field(ge=0, le=100)
    violence: int = Field(ge=0, le=100)
    romance: int = Field(ge=0, le=100)
    hopefulness: int = Field(ge=0, le=100)
    plot_complexity: int = Field(ge=0, le=100)
    rewatchability: int = Field(ge=0, le=100)


class MovieOut(BaseModel):
    """Public movie representation."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tmdb_id: int
    title: str
    overview: str | None = None
    release_year: int | None = None
    runtime: int | None = None
    genres: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    language: str | None = None
    poster_path: str | None = None
    vote_average: float | None = None
    vote_count: int | None = None
    popularity: float | None = None
    personality: MoviePersonalityOut | None = None


class HealthOut(BaseModel):
    """Health check response."""

    status: str
    version: str
    database: str
