"""messages.input_mode: whether a user message was typed or spoken.

Only a marker: the content is the transcript and no audio is stored.
Existing messages become "text".

Revision ID: 0009_message_input_mode
Revises: 0008_clone_voice
Create Date: 2026-09-30
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_message_input_mode"
down_revision: str | None = "0008_clone_voice"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("input_mode", sa.String(10), server_default="text", nullable=False))
    op.create_check_constraint("ck_messages_input_mode", "messages", "input_mode IN ('text', 'voice')")


def downgrade() -> None:
    op.drop_constraint("ck_messages_input_mode", "messages", type_="check")
    op.drop_column("messages", "input_mode")
