"""Conversation.source: "app" or "api" (started through the developer API).

Revision ID: 0018_conversation_source
Revises: 0017_analytics_events
Create Date: 2026-10-05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_conversation_source"
down_revision: str | None = "0017_analytics_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing conversations were all started in the app.
    op.add_column("conversations", sa.Column("source", sa.String(10), server_default="app", nullable=False))


def downgrade() -> None:
    op.drop_column("conversations", "source")
