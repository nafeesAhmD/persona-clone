"""AI agent (Phase 16): per-clone agent profile, tool permissions, executions and steps.

An agent never has general access to the server: it can only call the tools in
app/agent/tools, each checked against these permissions on every call. Execution
records hold short, safe summaries (no secrets, no full private messages, no
hidden reasoning).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

_JSON = JSON().with_variant(JSONB(), "postgresql")

EXECUTION_STATUSES = (
    "queued",
    "planning",
    "running",
    "waiting_confirmation",
    "completed",
    "failed",
    "cancelled",
    "timeout",
)
FINAL_STATUSES = ("completed", "failed", "cancelled", "timeout")
STEP_TYPES = ("plan", "tool", "confirmation", "memory_proposal", "final", "error")
STEP_STATUSES = ("running", "succeeded", "failed", "skipped", "waiting", "rejected")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class AgentProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One agent per clone. Disabled until the owner turns it on."""

    __tablename__ = "agent_profiles"
    __table_args__ = (
        UniqueConstraint("clone_id", name="uq_agent_profiles_clone_id"),
        CheckConstraint("max_steps BETWEEN 1 AND 50", name="ck_agent_profiles_max_steps"),
        CheckConstraint(
            "max_execution_time_seconds BETWEEN 5 AND 600", name="ck_agent_profiles_max_execution_time"
        ),
    )

    clone_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clone_profiles.id", ondelete="CASCADE"))
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100), default="AI Agent")
    description: Mapped[str | None] = mapped_column(String(500))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    max_steps: Mapped[int] = mapped_column(Integer, default=8, server_default="8")
    max_execution_time_seconds: Mapped[int] = mapped_column(Integer, default=60, server_default="60")
    require_confirmation_for_actions: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # Organization viewers may run the agent only when this is on (Phase 13 roles).
    allow_viewer_use: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class AgentToolPermission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Per-agent switch for one registered tool (a missing row = the tool's safe default)."""

    __tablename__ = "agent_tool_permissions"
    __table_args__ = (UniqueConstraint("agent_id", "tool_name", name="uq_agent_tool_permissions_agent_tool"),)

    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_profiles.id", ondelete="CASCADE"), index=True)
    tool_name: Mapped[str] = mapped_column(String(60))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    require_confirmation: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class AgentExecution(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_executions"
    __table_args__ = (
        CheckConstraint(_in("status", EXECUTION_STATUSES), name="ck_agent_executions_status"),
        CheckConstraint(_in("source", ("app", "api", "public")), name="ck_agent_executions_source"),
        Index("ix_agent_executions_clone_created", "clone_id", "created_at"),
        Index("ix_agent_executions_status", "status"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_profiles.id", ondelete="CASCADE"), index=True)
    clone_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clone_profiles.id", ondelete="CASCADE"))
    # Who asked (nullable: the account may be deleted later; API runs record the key too).
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("api_keys.id", ondelete="SET NULL"))
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"))
    source: Mapped[str] = mapped_column(String(10), default="app", server_default="app")
    status: Mapped[str] = mapped_column(String(24), default="queued", server_default="queued")
    goal: Mapped[str] = mapped_column(Text)
    current_step: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_steps: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    tool_calls: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    result_summary: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(String(500))
    # The one action waiting for the user: {action_id, tool, title, reason, risk, input_preview}.
    # A confirmation must quote this action_id; it's cleared once used (no replays).
    pending_action: Mapped[dict | None] = mapped_column(_JSON)
    # A memory the agent suggests saving: {proposal_id, content, memory_type}; saved only on "Save".
    memory_proposal: Mapped[dict | None] = mapped_column(_JSON)
    # The assistant message holding the final answer (chat/voice/avatar reuse it).
    final_message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentStep(UUIDPrimaryKeyMixin, Base):
    """One visible step: a short, safe summary of what the agent did (never hidden reasoning)."""

    __tablename__ = "agent_steps"
    __table_args__ = (
        UniqueConstraint("execution_id", "step_number", name="uq_agent_steps_execution_step"),
        CheckConstraint(_in("step_type", STEP_TYPES), name="ck_agent_steps_type"),
        CheckConstraint(_in("status", STEP_STATUSES), name="ck_agent_steps_status"),
    )

    execution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_executions.id", ondelete="CASCADE"), index=True)
    step_number: Mapped[int] = mapped_column(Integer)
    step_type: Mapped[str] = mapped_column(String(20))
    tool_name: Mapped[str | None] = mapped_column(String(60), index=True)
    # Safe metadata only (sizes, counts, titles, scores, the step's public summary).
    input_metadata: Mapped[dict] = mapped_column(_JSON, default=dict)
    output_metadata: Mapped[dict] = mapped_column(_JSON, default=dict)
    status: Mapped[str] = mapped_column(String(12), default="running", server_default="running")
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
