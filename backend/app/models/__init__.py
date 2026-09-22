"""SQLAlchemy ORM models for CineMind.

Schema notes:
- ``movies`` keeps TMDb's rich, evolving payload in JSONB (``raw``) while
  promoting the columns we query/score on (genres, ratings, popularity...).
- The ``embedding`` column is ``pgvector``'s ``Vector`` (module 2 fills it;
  it is nullable until then).
- ``movie_personality`` holds module 7's nine 0-100 trait scores.
"""

import datetime
import uuid
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)

from app.core.config import get_settings


class Base(DeclarativeBase):
    """Base class for all ORM models."""


def _vector_column() -> Vector:
    """Embedding column sized from settings (text-embedding-3-large truncated)."""
    return Vector(dim=get_settings().embedding_dimensions)


class Movie(Base):
    """A movie ingested from TMDb."""

    __tablename__ = "movies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tmdb_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    title: Mapped[str] = mapped_column(Text)
    original_title: Mapped[str | None] = mapped_column(Text)
    overview: Mapped[str | None] = mapped_column(Text)
    tagline: Mapped[str | None] = mapped_column(Text)
    release_date: Mapped[datetime.date | None]
    runtime_minutes: Mapped[int | None]
    genres: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    keywords: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    vote_average: Mapped[float | None] = mapped_column(Float)
    vote_count: Mapped[int | None] = mapped_column(Integer)
    popularity: Mapped[float | None] = mapped_column(Float)
    original_language: Mapped[str | None] = mapped_column(String(16))
    poster_path: Mapped[str | None] = mapped_column(Text)
    backdrop_path: Mapped[str | None] = mapped_column(Text)
    embedding = mapped_column(_vector_column(), nullable=True)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    personality: Mapped["MoviePersonality | None"] = relationship(
        back_populates="movie", uselist=False, cascade="all, delete-orphan"
    )


class MoviePersonality(Base):
    """Module 7: nine personality trait scores (0-100) for a movie."""

    __tablename__ = "movie_personality"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    movie_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("movies.id", ondelete="CASCADE"), unique=True, index=True
    )
    emotion: Mapped[float] = mapped_column(Float, default=50)
    mind_blowing: Mapped[float] = mapped_column(Float, default=50)
    darkness: Mapped[float] = mapped_column(Float, default=50)
    humor: Mapped[float] = mapped_column(Float, default=50)
    violence: Mapped[float] = mapped_column(Float, default=50)
    romance: Mapped[float] = mapped_column(Float, default=50)
    hopefulness: Mapped[float] = mapped_column(Float, default=50)
    plot_complexity: Mapped[float] = mapped_column(Float, default=50)
    rewatchability: Mapped[float] = mapped_column(Float, default=50)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    movie: Mapped[Movie] = relationship(back_populates="personality")


class User(Base):
    """A CineMind user (module 6 attaches a taste profile)."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    display_name: Mapped[str] = mapped_column(Text, default="Anonymous")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    ratings: Mapped[list["Rating"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    taste_profile: Mapped["TasteProfile | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class Rating(Base):
    """A user's like/dislike of a movie (1-10 scale)."""

    __tablename__ = "ratings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    movie_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("movies.id", ondelete="CASCADE"), index=True
    )
    score: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="ratings")
    movie: Mapped[Movie] = relationship()


class TasteProfile(Base):
    """Module 6: evolving user taste summary."""

    __tablename__ = "taste_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    liked_genres: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    disliked_genres: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    liked_themes: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    disliked_themes: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    embedding = mapped_column(_vector_column(), nullable=True)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="taste_profile")
