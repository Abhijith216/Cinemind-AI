"""SQLAlchemy ORM models for CineMind.

Design notes (agreed schema):
- ``movies`` is a flat table: scoring attributes as columns, flexible
  attributes (``genres``, ``keywords``) as JSONB arrays, the nine personality
  traits as one JSONB object (each 0-100 int — enforced in the Pydantic
  layer, not the DB), and a fixed ``vector(1536)`` embedding for pgvector.
- ``users`` carries auth columns now (``email`` unique, ``hashed_password``);
  JWT wiring arrives with the auth module.
- ``ratings.score`` is an int 1-10 with a CHECK constraint; one rating per
  (user, movie) — re-rating upserts via ON CONFLICT.
- ``user_taste_profiles`` is 1:1 with users (unique user_id).
- ``taste_snapshots`` keeps one row per user per month for the taste-evolution
chart (unique (user_id, month)).
- ``chat_sessions``/``chat_messages`` (Module 8) persist multi-turn
conversations: messages store the resolved intent payload and the
ordered movie ids shown, so any turn can be replayed or audited.

Indexes: GIN on every JSONB column we filter into, HNSW (cosine) on
``movies.embedding`` once the table has data.
"""

import datetime
import uuid
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


class Base(DeclarativeBase):
    """Base class for all ORM models."""


EMBEDDING_DIMENSIONS = 1536

_PERSONALITY_TRAITS: tuple[str, ...] = (
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


class Movie(Base):
    """A movie ingested from TMDb."""

    __tablename__ = "movies"
    __table_args__ = (
        Index("ix_movies_genres_gin", "genres", postgresql_using="gin"),
        Index("ix_movies_keywords_gin", "keywords", postgresql_using="gin"),
        Index(
            "ix_movies_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tmdb_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    title: Mapped[str] = mapped_column(Text)
    overview: Mapped[str | None] = mapped_column(Text)
    release_year: Mapped[int | None] = mapped_column(Integer)
    runtime: Mapped[int | None] = mapped_column(Integer)
    genres: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)
    keywords: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)
    language: Mapped[str | None] = mapped_column(String(16))
    poster_path: Mapped[str | None] = mapped_column(Text)
    vote_average: Mapped[float | None] = mapped_column(Float)
    vote_count: Mapped[int | None] = mapped_column(Integer)
    popularity: Mapped[float | None] = mapped_column(Float)
    embedding = mapped_column(
        Vector(dim=EMBEDDING_DIMENSIONS), nullable=True
    )
    personality: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    ratings: Mapped[list["Rating"]] = relationship(back_populates="movie")


class User(Base):
    """A CineMind user."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(Text, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    ratings: Mapped[list["Rating"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    taste_profile: Mapped["UserTasteProfile | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    taste_snapshots: Mapped[list["TasteSnapshot"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserTasteProfile(Base):
    """Module 6: the user's current taste profile (1:1 with users)."""

    __tablename__ = "user_taste_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    likes: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)
    dislikes: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)
    favorite_themes: Mapped[list[Any]] = mapped_column(
        JSONB, default=list, nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="taste_profile")


class Rating(Base):
    """A user's rating of a movie (1-10)."""

    __tablename__ = "ratings"
    __table_args__ = (
        CheckConstraint("score >= 1 AND score <= 10", name="ck_ratings_score_range"),
        # One rating per (user, movie); re-rating upserts via ON CONFLICT.
        Index(
            "uq_ratings_user_movie",
            "user_id",
            "movie_id",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    movie_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("movies.id", ondelete="CASCADE"), index=True
    )
    score: Mapped[int] = mapped_column(Integer)
    rated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="ratings")
    movie: Mapped[Movie] = relationship(back_populates="ratings")


class TasteSnapshot(Base):
    """Module 9 chart data: monthly taste snapshot per user."""

    __tablename__ = "taste_snapshots"
    __table_args__ = (
        # One snapshot per user per month ("2026-09" style values).
        Index("uq_taste_snapshots_user_month", "user_id", "month", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    month: Mapped[str] = mapped_column(String(7))
    dominant_genres: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)
    dominant_themes: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="taste_snapshots")


class ChatSession(Base):
    """Module 8: one conversation between a user and CineMind."""

    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )


class ChatMessage(Base):
    """One turn (user or assistant) inside a chat session.

    Assistant turns optionally carry the resolved ``intent`` payload and the
    ordered ``result_movie_ids`` that were shown, so results are auditable
    and the Phase 14 UI can re-render a past turn.
    """

    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text)
    intent: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    result_movie_ids: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session: Mapped[ChatSession] = relationship(back_populates="messages")
