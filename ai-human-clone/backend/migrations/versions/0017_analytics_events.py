"""Create analytics_events (the Phase 11 model had no migration).

Revision ID: 0017_analytics_events
Revises: 0016_developer_platform
Create Date: 2026-10-05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_analytics_events"
down_revision: str | None = "0016_developer_platform"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "analytics_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("clone_id", sa.Uuid(), nullable=True),
        sa.Column("session_id", sa.String(100), nullable=True),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("source", sa.String(40), nullable=True),
        sa.Column("metadata", JSON, nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    for column in ("clone_id", "user_id", "event_type", "created_at", "session_id"):
        op.create_index(f"ix_analytics_events_{column}", "analytics_events", [column])
    op.create_index("ix_analytics_events_clone_created", "analytics_events", ["clone_id", "created_at"])


def downgrade() -> None:
    op.drop_table("analytics_events")
