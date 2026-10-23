"""Personal voice clone fields on clone_profiles.

Revision ID: 0020_voice_clone
Revises: 0019_ai_agent
Create Date: 2026-10-06
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_voice_clone"
down_revision: str | None = "0019_ai_agent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("clone_profiles", sa.Column("voice_clone_id", sa.String(100), nullable=True))
    op.add_column(
        "clone_profiles", sa.Column("voice_clone_status", sa.String(12), server_default="none", nullable=False)
    )
    op.add_column("clone_profiles", sa.Column("voice_clone_error", sa.String(300), nullable=True))
    op.add_column("clone_profiles", sa.Column("voice_clone_consent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "clone_profiles", sa.Column("use_cloned_voice", sa.Boolean(), server_default=sa.false(), nullable=False)
    )


def downgrade() -> None:
    for column in ("use_cloned_voice", "voice_clone_consent_at", "voice_clone_error", "voice_clone_status", "voice_clone_id"):
        op.drop_column("clone_profiles", column)
