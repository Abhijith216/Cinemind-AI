"""Indexed search documents and database-wide rate limit counters."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "movies",
        sa.Column(
            "search_document",
            postgresql.TSVECTOR(),
            sa.Computed(
                """
        setweight(to_tsvector('english'::regconfig, title), 'A') ||
        setweight(to_tsvector('english'::regconfig, genres::text || ' ' || keywords::text), 'B') ||
        setweight(to_tsvector('english'::regconfig, coalesce(overview, '')), 'C')
    """,
                persisted=True,
            ),
        ),
    )
    op.create_index(
        "ix_movies_search_document_gin", "movies", ["search_document"], postgresql_using="gin"
    )
    op.create_table(
        "rate_limit_buckets",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("bucket", sa.BigInteger(), primary_key=True),
        sa.Column("hits", sa.Integer(), nullable=False),
    )
    op.create_index("ix_rate_limit_buckets_bucket", "rate_limit_buckets", ["bucket"])
    op.create_index(
        "ix_chat_sessions_user_updated", "chat_sessions", ["user_id", "updated_at", "id"]
    )


def downgrade() -> None:
    op.drop_index("ix_chat_sessions_user_updated", table_name="chat_sessions")
    op.drop_table("rate_limit_buckets")
    op.drop_index("ix_movies_search_document_gin", table_name="movies")
    op.drop_column("movies", "search_document")
