"""AI agent: profiles, tool permissions, executions, steps; clone_profiles.public_agent_enabled.

Revision ID: 0019_ai_agent
Revises: 0018_conversation_source
Create Date: 2026-10-06
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019_ai_agent"
down_revision: str | None = "0018_conversation_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
EXECUTION_STATUSES = "'queued', 'planning', 'running', 'waiting_confirmation', 'completed', 'failed', 'cancelled', 'timeout'"


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.add_column(
        "clone_profiles", sa.Column("public_agent_enabled", sa.Boolean(), server_default=sa.false(), nullable=False)
    )

    op.create_table(
        "agent_profiles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("clone_id", sa.Uuid(), sa.ForeignKey("clone_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("max_steps", sa.Integer(), server_default="8", nullable=False),
        sa.Column("max_execution_time_seconds", sa.Integer(), server_default="60", nullable=False),
        sa.Column("require_confirmation_for_actions", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("allow_viewer_use", sa.Boolean(), server_default=sa.false(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("clone_id", name="uq_agent_profiles_clone_id"),
        sa.CheckConstraint("max_steps BETWEEN 1 AND 50", name="ck_agent_profiles_max_steps"),
        sa.CheckConstraint("max_execution_time_seconds BETWEEN 5 AND 600", name="ck_agent_profiles_max_execution_time"),
    )
    op.create_index("ix_agent_profiles_owner_id", "agent_profiles", ["owner_id"])

    op.create_table(
        "agent_tool_permissions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agent_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tool_name", sa.String(60), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("require_confirmation", sa.Boolean(), server_default=sa.false(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("agent_id", "tool_name", name="uq_agent_tool_permissions_agent_tool"),
    )
    op.create_index("ix_agent_tool_permissions_agent_id", "agent_tool_permissions", ["agent_id"])

    op.create_table(
        "agent_executions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agent_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("clone_id", sa.Uuid(), sa.ForeignKey("clone_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("api_key_id", sa.Uuid(), sa.ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source", sa.String(10), server_default="app", nullable=False),
        sa.Column("status", sa.String(24), server_default="queued", nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("current_step", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_steps", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tool_calls", sa.Integer(), server_default="0", nullable=False),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("error_message", sa.String(500), nullable=True),
        sa.Column("pending_action", JSON, nullable=True),
        sa.Column("memory_proposal", JSON, nullable=True),
        sa.Column("final_message_id", sa.Uuid(), sa.ForeignKey("messages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(f"status IN ({EXECUTION_STATUSES})", name="ck_agent_executions_status"),
        sa.CheckConstraint("source IN ('app', 'api', 'public')", name="ck_agent_executions_source"),
    )
    op.create_index("ix_agent_executions_agent_id", "agent_executions", ["agent_id"])
    op.create_index("ix_agent_executions_user_id", "agent_executions", ["user_id"])
    op.create_index("ix_agent_executions_clone_created", "agent_executions", ["clone_id", "created_at"])
    op.create_index("ix_agent_executions_status", "agent_executions", ["status"])

    op.create_table(
        "agent_steps",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("execution_id", sa.Uuid(), sa.ForeignKey("agent_executions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("step_type", sa.String(20), nullable=False),
        sa.Column("tool_name", sa.String(60), nullable=True),
        sa.Column("input_metadata", JSON, nullable=False),
        sa.Column("output_metadata", JSON, nullable=False),
        sa.Column("status", sa.String(12), server_default="running", nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("execution_id", "step_number", name="uq_agent_steps_execution_step"),
        sa.CheckConstraint(
            "step_type IN ('plan', 'tool', 'confirmation', 'memory_proposal', 'final', 'error')",
            name="ck_agent_steps_type",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'skipped', 'waiting', 'rejected')",
            name="ck_agent_steps_status",
        ),
    )
    op.create_index("ix_agent_steps_execution_id", "agent_steps", ["execution_id"])
    op.create_index("ix_agent_steps_tool_name", "agent_steps", ["tool_name"])


def downgrade() -> None:
    op.drop_table("agent_steps")
    op.drop_table("agent_executions")
    op.drop_table("agent_tool_permissions")
    op.drop_table("agent_profiles")
    op.drop_column("clone_profiles", "public_agent_enabled")
