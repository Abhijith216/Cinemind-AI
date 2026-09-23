"""Module 6 schemas — ratings and taste profile (request/response contracts)."""

import datetime
import uuid

from pydantic import BaseModel, Field


class RatingCreate(BaseModel):
    """Body of POST /ratings."""

    user_id: uuid.UUID
    movie_id: uuid.UUID
    score: int = Field(ge=1, le=10, description="1 = hated it, 10 = masterpiece")


class RatingOut(BaseModel):
    """Response for POST /ratings."""

    id: uuid.UUID
    user_id: uuid.UUID
    movie_id: uuid.UUID
    score: int
    rated_at: datetime.datetime
    created: bool  # False when an existing rating was upserted


class TasteProfileOut(BaseModel):
    """Current taste profile (GET /taste-profile/{user_id})."""

    user_id: uuid.UUID
    likes: list[str] = Field(default_factory=list)
    dislikes: list[str] = Field(default_factory=list)
    favorite_themes: list[str] = Field(default_factory=list)
    updated_at: datetime.datetime | None = None


class TasteSnapshotOut(BaseModel):
    """One monthly snapshot row (Phase 14 taste-evolution chart data)."""

    user_id: uuid.UUID
    month: str  # "2026-09"
    dominant_genres: list[str] = Field(default_factory=list)
    dominant_themes: list[str] = Field(default_factory=list)
    created_at: datetime.datetime | None = None
