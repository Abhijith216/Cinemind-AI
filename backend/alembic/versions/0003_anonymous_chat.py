"""Allow anonymous chat sessions without changing existing records.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-21
"""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("chat_sessions", "user_id", nullable=True)


def downgrade() -> None:
    # Preserve anonymous conversations rather than deleting them on downgrade.
    count = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM chat_sessions WHERE user_id IS NULL")
    )
    if count:
        raise RuntimeError("Cannot require user_id while anonymous chat sessions exist")
    op.alter_column("chat_sessions", "user_id", nullable=False)
