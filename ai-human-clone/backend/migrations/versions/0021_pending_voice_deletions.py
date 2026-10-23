"""Cloned voices still waiting to be deleted at a provider.

Revision ID: 0021_pending_voice_deletions
Revises: 0020_voice_clone
Create Date: 2026-10-08
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_pending_voice_deletions"
down_revision: str | None = "0020_voice_clone"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pending_voice_deletions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("voice_clone_id", sa.String(100), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("voice_clone_id", name="uq_pending_voice_deletions_voice_clone_id"),
    )


def downgrade() -> None:
    op.drop_table("pending_voice_deletions")
