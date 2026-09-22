"""Initial CineMind schema (movies, users, taste profiles, ratings, snapshots).

Revision ID: 0001
Revises:
Create Date: 2026-09-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_EMBEDDING_DIM = 1536


def upgrade() -> None:
    # pgvector must exist before any vector column is created.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "movies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tmdb_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("overview", sa.Text(), nullable=True),
        sa.Column("release_year", sa.Integer(), nullable=True),
        sa.Column("runtime", sa.Integer(), nullable=True),
        sa.Column("genres", JSONB(), nullable=False, server_default="[]"),
        sa.Column("keywords", JSONB(), nullable=False, server_default="[]"),
        sa.Column("language", sa.String(16), nullable=True),
        sa.Column("poster_path", sa.Text(), nullable=True),
        sa.Column("vote_average", sa.Float(), nullable=True),
        sa.Column("vote_count", sa.Integer(), nullable=True),
        sa.Column("popularity", sa.Float(), nullable=True),
        sa.Column(
            "embedding", Vector(dim=_EMBEDDING_DIM), nullable=True
        ),
        sa.Column("personality", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_movies_tmdb_id", "movies", ["tmdb_id"], unique=True)
    op.create_index("ix_movies_genres_gin", "movies", ["genres"], postgresql_using="gin")
    op.create_index("ix_movies_keywords_gin", "movies", ["keywords"], postgresql_using="gin")
    op.create_index(
        "ix_movies_embedding_hnsw",
        "movies",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("hashed_password", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "user_taste_profiles",
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("likes", JSONB(), nullable=False, server_default="[]"),
        sa.Column("dislikes", JSONB(), nullable=False, server_default="[]"),
        sa.Column("favorite_themes", JSONB(), nullable=False, server_default="[]"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "ratings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "movie_id",
            UUID(as_uuid=True),
            sa.ForeignKey("movies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("rated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("score >= 1 AND score <= 10", name="ck_ratings_score_range"),
    )
    op.create_index("ix_ratings_user_id", "ratings", ["user_id"])
    op.create_index("ix_ratings_movie_id", "ratings", ["movie_id"])
    op.create_index(
        "uq_ratings_user_movie", "ratings", ["user_id", "movie_id"], unique=True
    )

    op.create_table(
        "taste_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("month", sa.String(7), nullable=False),
        sa.Column("dominant_genres", JSONB(), nullable=False, server_default="[]"),
        sa.Column("dominant_themes", JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_taste_snapshots_user_id", "taste_snapshots", ["user_id"])
    op.create_index(
        "uq_taste_snapshots_user_month",
        "taste_snapshots",
        ["user_id", "month"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_table("taste_snapshots")
    op.drop_table("ratings")
    op.drop_table("user_taste_profiles")
    op.drop_table("users")
    op.drop_table("movies")
    op.execute("DROP EXTENSION IF EXISTS vector")
