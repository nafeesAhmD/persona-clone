"""Public clones: public settings, content visibility, visitor sessions.

- clone_profiles: public_chat_enabled / public_voice_enabled / public_avatar_enabled,
  all off, so no existing clone becomes reachable by anonymous visitors.
- documents.visibility and clone_memories.visibility: "private" for every
  existing row; only content the owner marks "public" reaches visitors.
- public_chat_sessions / public_chat_messages: anonymous visitor conversations.
- avatar_video_jobs.public_session_id: visitor videos belong to their session.

Revision ID: 0011_public_clones
Revises: 0010_clone_avatars
Create Date: 2026-10-01
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_public_clones"
down_revision: str | None = "0010_clone_avatars"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    for column in ("public_chat_enabled", "public_voice_enabled", "public_avatar_enabled"):
        op.add_column("clone_profiles", sa.Column(column, sa.Boolean(), server_default=sa.false(), nullable=False))

    op.add_column("documents", sa.Column("visibility", sa.String(10), server_default="private", nullable=False))
    op.create_check_constraint("ck_documents_visibility", "documents", "visibility IN ('private', 'public')")
    op.create_index("ix_documents_clone_visibility", "documents", ["clone_id", "visibility"])

    op.add_column("clone_memories", sa.Column("visibility", sa.String(10), server_default="private", nullable=False))
    op.create_check_constraint("ck_clone_memories_visibility", "clone_memories", "visibility IN ('private', 'public')")
    op.create_index("ix_clone_memories_visibility", "clone_memories", ["visibility"])

    op.create_table(
        "public_chat_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("clone_id", sa.Uuid(), sa.ForeignKey("clone_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_public_chat_sessions_clone_id", "public_chat_sessions", ["clone_id"])
    op.create_index("ix_public_chat_sessions_expires_at", "public_chat_sessions", ["expires_at"])

    op.create_table(
        "public_chat_messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "session_id", sa.Uuid(), sa.ForeignKey("public_chat_sessions.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("input_mode", sa.String(10), server_default="text", nullable=False),
        *_timestamps(),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_public_chat_messages_role"),
    )
    op.create_index("ix_public_chat_messages_session_id", "public_chat_messages", ["session_id"])
    op.create_index("ix_public_chat_messages_session_created", "public_chat_messages", ["session_id", "created_at"])

    op.add_column("avatar_video_jobs", sa.Column("public_session_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "avatar_video_jobs_public_session_id_fkey",
        "avatar_video_jobs",
        "public_chat_sessions",
        ["public_session_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_avatar_video_jobs_public_session_id", "avatar_video_jobs", ["public_session_id"])
    op.add_column("avatar_video_jobs", sa.Column("public_message_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "avatar_video_jobs_public_message_id_fkey",
        "avatar_video_jobs",
        "public_chat_messages",
        ["public_message_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("avatar_video_jobs_public_message_id_fkey", "avatar_video_jobs", type_="foreignkey")
    op.drop_column("avatar_video_jobs", "public_message_id")
    op.drop_index("ix_avatar_video_jobs_public_session_id", table_name="avatar_video_jobs")
    op.drop_constraint("avatar_video_jobs_public_session_id_fkey", "avatar_video_jobs", type_="foreignkey")
    op.drop_column("avatar_video_jobs", "public_session_id")
    op.drop_table("public_chat_messages")
    op.drop_table("public_chat_sessions")
    op.drop_index("ix_clone_memories_visibility", table_name="clone_memories")
    op.drop_constraint("ck_clone_memories_visibility", "clone_memories", type_="check")
    op.drop_column("clone_memories", "visibility")
    op.drop_index("ix_documents_clone_visibility", table_name="documents")
    op.drop_constraint("ck_documents_visibility", "documents", type_="check")
    op.drop_column("documents", "visibility")
    for column in ("public_avatar_enabled", "public_voice_enabled", "public_chat_enabled"):
        op.drop_column("clone_profiles", column)
