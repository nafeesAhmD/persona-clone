"""Conversation ownership and message metadata.

- conversations.user_id: every conversation belongs to one user. Existing
  conversations (from when chat didn't require login) are assigned to the
  clone's owner, so no one else can read them.
- messages: retrieved_chunks_count, model_name, latency_ms (assistant replies),
  a role check, and indexes for history and sidebar queries.

Revision ID: 0006_conversations
Revises: 0005_document_indexing
Create Date: 2026-09-30
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_conversations"
down_revision: str | None = "0005_document_indexing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("user_id", sa.Uuid(), nullable=True))
    op.execute(
        "UPDATE conversations c SET user_id = p.owner_id FROM clone_profiles p WHERE p.id = c.clone_id"
    )
    op.alter_column("conversations", "user_id", nullable=False)
    op.create_foreign_key(
        "conversations_user_id_fkey", "conversations", "users", ["user_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
    op.create_index("ix_conversations_user_clone_updated", "conversations", ["user_id", "clone_id", "updated_at"])

    op.add_column("messages", sa.Column("retrieved_chunks_count", sa.Integer(), nullable=True))
    op.add_column("messages", sa.Column("model_name", sa.String(100), nullable=True))
    op.add_column("messages", sa.Column("latency_ms", sa.Integer(), nullable=True))
    op.create_check_constraint("ck_messages_role", "messages", "role IN ('user', 'assistant')")
    op.create_index("ix_messages_conversation_created", "messages", ["conversation_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_messages_conversation_created", table_name="messages")
    op.drop_constraint("ck_messages_role", "messages", type_="check")
    for column in ("latency_ms", "model_name", "retrieved_chunks_count"):
        op.drop_column("messages", column)
    op.drop_index("ix_conversations_user_clone_updated", table_name="conversations")
    op.drop_index("ix_conversations_user_id", table_name="conversations")
    op.drop_constraint("conversations_user_id_fkey", "conversations", type_="foreignkey")
    op.drop_column("conversations", "user_id")
