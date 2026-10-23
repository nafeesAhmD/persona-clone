"""Avatars and talking-avatar video jobs.

- clone_profiles: avatar_enabled, avatar_consent_given, avatar_consent_at
  (avatar on requires consent; existing clones start with it off).
- clone_avatars: avatar images of a clone (files on disk, names generated).
- avatar_video_jobs: background lip-sync jobs and their output file names.

Revision ID: 0010_clone_avatars
Revises: 0009_message_input_mode
Create Date: 2026-09-30
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_clone_avatars"
down_revision: str | None = "0009_message_input_mode"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.add_column("clone_profiles", sa.Column("avatar_enabled", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column(
        "clone_profiles", sa.Column("avatar_consent_given", sa.Boolean(), server_default=sa.false(), nullable=False)
    )
    op.add_column("clone_profiles", sa.Column("avatar_consent_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_clone_profiles_avatar_consent", "clone_profiles", "NOT avatar_enabled OR avatar_consent_given"
    )

    op.create_table(
        "clone_avatars",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("clone_id", sa.Uuid(), sa.ForeignKey("clone_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("image_path", sa.String(64), nullable=False),
        sa.Column("avatar_type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("mouth_x", sa.Float(), nullable=False),
        sa.Column("mouth_y", sa.Float(), nullable=False),
        sa.Column("mouth_width", sa.Float(), nullable=False),
        sa.Column("face_detected", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("error_message", sa.String(300), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("avatar_type IN ('uploaded', 'generated', 'preset')", name="ck_clone_avatars_type"),
        sa.CheckConstraint("status IN ('pending', 'processing', 'ready', 'failed')", name="ck_clone_avatars_status"),
    )
    op.create_index("ix_clone_avatars_clone_id", "clone_avatars", ["clone_id"])
    op.create_index("ix_clone_avatars_owner_id", "clone_avatars", ["owner_id"])
    op.create_index("ix_clone_avatars_clone_active", "clone_avatars", ["clone_id", "is_active"])

    op.create_table(
        "avatar_video_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("clone_id", sa.Uuid(), sa.ForeignKey("clone_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True),
        sa.Column("message_id", sa.Uuid(), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=True),
        sa.Column("avatar_id", sa.Uuid(), sa.ForeignKey("clone_avatars.id", ondelete="SET NULL"), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("input_audio_path", sa.String(64), nullable=True),
        sa.Column("output_video_path", sa.String(64), nullable=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.String(300), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'failed', 'cancelled')", name="ck_avatar_video_jobs_status"
        ),
        sa.CheckConstraint("progress >= 0 AND progress <= 100", name="ck_avatar_video_jobs_progress"),
    )
    for column in ("clone_id", "owner_id", "conversation_id", "message_id", "status"):
        op.create_index(f"ix_avatar_video_jobs_{column}", "avatar_video_jobs", [column])
    op.create_index("ix_avatar_video_jobs_clone_created", "avatar_video_jobs", ["clone_id", "created_at"])


def downgrade() -> None:
    op.drop_table("avatar_video_jobs")
    op.drop_table("clone_avatars")
    op.drop_constraint("ck_clone_profiles_avatar_consent", "clone_profiles", type_="check")
    for column in ("avatar_consent_at", "avatar_consent_given", "avatar_enabled"):
        op.drop_column("clone_profiles", column)
