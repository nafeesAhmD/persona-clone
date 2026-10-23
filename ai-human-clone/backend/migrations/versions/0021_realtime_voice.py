"""Real-time voice (Phase 17): clone switches and realtime_voice_sessions.

Revision ID: 0021_realtime_voice
Revises: 0021_pending_voice_deletions
Create Date: 2026-10-09
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021_realtime_voice"
down_revision: str | None = "0021_pending_voice_deletions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
_STATUSES = "status IN ('created', 'connecting', 'connected', 'ended', 'failed', 'expired')"


def upgrade() -> None:
    op.add_column(
        "clone_profiles", sa.Column("realtime_voice_enabled", sa.Boolean(), server_default=sa.true(), nullable=False)
    )
    op.add_column(
        "clone_profiles",
        sa.Column("public_realtime_voice_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "clone_profiles", sa.Column("realtime_speech_mode", sa.String(16), server_default="voice", nullable=False)
    )
    op.create_table(
        "realtime_voice_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("clone_id", sa.Uuid(), sa.ForeignKey("clone_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("visitor_key", sa.String(64), nullable=True),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("status", sa.String(12), server_default="created", nullable=False),
        sa.Column("is_public", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("turns", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(40), nullable=True),
        sa.Column("metadata", _JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("ticket_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(_STATUSES, name="ck_realtime_voice_sessions_status"),
    )
    op.create_index("ix_realtime_voice_sessions_clone_id", "realtime_voice_sessions", ["clone_id"])
    op.create_index("ix_realtime_voice_sessions_owner_created", "realtime_voice_sessions", ["owner_id", "created_at"])
    op.create_index("ix_realtime_voice_sessions_status", "realtime_voice_sessions", ["status"])


def downgrade() -> None:
    op.drop_table("realtime_voice_sessions")
    for column in ("realtime_speech_mode", "public_realtime_voice_enabled", "realtime_voice_enabled"):
        op.drop_column("clone_profiles", column)
