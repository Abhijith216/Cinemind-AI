"""Movie + user Pydantic schemas (shared request/response contracts)."""

import datetime
import uuid

from pydantic import BaseModel, ConfigDict, Field


class MovieOut(BaseModel):
    """Public movie representation."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tmdb_id: int
    title: str
    overview: str | None = None
    tagline: str | None = None
    release_date: datetime.date | None = None
    runtime_minutes: int | None = None
    genres: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    vote_average: float | None = None
    vote_count: int | None = None
    popularity: float | None = None
    original_language: str | None = None
    poster_path: str | None = None
    backdrop_path: str | None = None


class HealthOut(BaseModel):
    """Health check response."""

    status: str
    version: str
    database: str
