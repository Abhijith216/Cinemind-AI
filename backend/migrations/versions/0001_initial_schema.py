"""Initial CineMind schema (movies, personalities, users, ratings, taste profiles).

Revision ID: 0001
Revises:
Create Date: 2026-09-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from cinemind.core.config import get_settings

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PERSONALITY_TRAITS = (
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


def upgrade() -> None:
    # pgvector must exist before any Vector column is created.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "movies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tmdb_id", sa.Integer(), nullable=False, unique=True, index=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("original_title", sa.Text(), nullable=True),
        sa.Column("overview", sa.Text(), nullable=True),
        sa.Column("tagline", sa.Text(), nullable=True),
        sa.Column("release_date", sa.Date(), nullable=True),
        sa.Column("runtime_minutes", sa.Integer(), nullable=True),
        sa.Column("genres", ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("keywords", ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("vote_average", sa.Float(), nullable=True),
        sa.Column("vote_count", sa.Integer(), nullable=True),
        sa.Column("popularity", sa.Float(), nullable=True),
        sa.Column("original_language", sa.String(16), nullable=True),
        sa.Column("poster_path", sa.Text(), nullable=True),
        sa.Column("backdrop_path", sa.Text(), nullable=True),
        sa.Column(
            "embedding",
            Vector(dim=get_settings().embedding_dimensions),
            nullable=True,
        ),
        sa.Column("raw", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "movie_personality",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "movie_id",
            UUID(as_uuid=True),
            sa.ForeignKey("movies.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        *[
            sa.Column(trait, sa.Float(), nullable=False, server_default="50")
            for trait in _PERSONALITY_TRAITS
        ],
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_movie_personality_movie_id", "movie_personality", ["movie_id"])

    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("display_name", sa.Text(), nullable=False, server_default="Anonymous"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "ratings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "movie_id", UUID(as_uuid=True), sa.ForeignKey("movies.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_ratings_user_id", "ratings", ["user_id"])
    op.create_index("ix_ratings_movie_id", "ratings", ["movie_id"])

    op.create_table(
        "taste_profiles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
        ),
        sa.Column("liked_genres", ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("disliked_genres", ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("liked_themes", ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("disliked_themes", ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "embedding",
            Vector(dim=get_settings().embedding_dimensions),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("taste_profiles")
    op.drop_table("ratings")
    op.drop_table("users")
    op.drop_table("movie_personality")
    op.drop_table("movies")
