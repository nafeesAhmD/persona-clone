"""Long-term memory: the clone_memories table.

A memory belongs to one clone and its owner. Conversation-derived memories
start as "candidate" and are only used after the owner approves them.

Revision ID: 0007_clone_memories
Revises: 0006_conversations
Create Date: 2026-09-30
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_clone_memories"
down_revision: str | None = "0006_conversations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MEMORY_TYPES = (
    "fact",
    "preference",
    "communication_preference",
    "skill",
    "experience",
    "project",
    "goal",
    "background",
    "instruction",
    "other",
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.create_table(
        "clone_memories",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("clone_id", sa.Uuid(), sa.ForeignKey("clone_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("memory_type", sa.String(40), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column(
            "source_conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(_in("memory_type", MEMORY_TYPES), name="ck_clone_memories_memory_type"),
        sa.CheckConstraint(_in("status", ("candidate", "approved", "rejected", "archived")), name="ck_clone_memories_status"),
        sa.CheckConstraint(_in("source", ("conversation", "manual")), name="ck_clone_memories_source"),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="ck_clone_memories_confidence"
        ),
    )
    for column in ("clone_id", "owner_id", "memory_type", "status", "source_conversation_id", "created_at"):
        op.create_index(f"ix_clone_memories_{column}", "clone_memories", [column])
    op.create_index("ix_clone_memories_clone_status_created", "clone_memories", ["clone_id", "status", "created_at"])


def downgrade() -> None:
    op.drop_table("clone_memories")  # drops its indexes and constraints too
