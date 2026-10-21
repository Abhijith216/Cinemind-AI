"""Track resumable catalog refresh attempts separately from successful syncs."""

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("movies", sa.Column("tmdb_checked_at", sa.DateTime(timezone=True)))
    op.add_column("movies", sa.Column("tmdb_synced_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("movies", "tmdb_synced_at")
    op.drop_column("movies", "tmdb_checked_at")
