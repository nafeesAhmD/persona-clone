"""Request/response shapes of the AI agent API (Phase 16; see docs/phase16/contract.md).

Responses never carry secrets, raw tool output or hidden reasoning: steps expose only a
short public summary. Requests forbid unknown fields (no mass assignment).
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Profile and tools ----------------------------------------------------------------


class ToolSettingRead(BaseModel):
    name: str
    title: str
    description: str
    risk: str
    permission_scope: str
    enabled: bool
    require_confirmation: bool
    available: bool
    reason_unavailable: str | None = None


class AgentLimits(BaseModel):
    max_steps: int
    max_execution_time_seconds: int
    max_tool_calls: int


class AgentProfileRead(BaseModel):
    id: uuid.UUID
    clone_id: uuid.UUID
    name: str
    description: str | None
    enabled: bool
    max_steps: int
    max_execution_time_seconds: int
    require_confirmation_for_actions: bool
    allow_viewer_use: bool
    public_agent_enabled: bool
    platform_enabled: bool
    can_configure: bool
    can_run: bool
    limits: AgentLimits
    tools: list[ToolSettingRead]


class AgentProfileUpdate(_Strict):
    """Only the fields listed here can change; anything else is a 400."""

    enabled: bool | None = None
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    # Upper bounds are checked against the server's AGENT_MAX_* settings in the route.
    max_steps: int | None = Field(default=None, ge=1, le=50)
    max_execution_time_seconds: int | None = Field(default=None, ge=5, le=600)
    require_confirmation_for_actions: bool | None = None
    allow_viewer_use: bool | None = None
    public_agent_enabled: bool | None = None


class ToolSettingUpdate(_Strict):
    enabled: bool
    # Omitted = keep the current confirmation setting.
    require_confirmation: bool | None = None


# --- Runs and executions --------------------------------------------------------------


class AgentRunRequest(_Strict):
    goal: str = Field(min_length=1, max_length=4000)
    conversation_id: uuid.UUID | None = None
    input_mode: Literal["text", "voice"] = "text"


class AgentRunResponse(BaseModel):
    execution_id: uuid.UUID
    status: str


class PendingAction(BaseModel):
    action_id: str
    tool: str
    title: str
    reason: str | None = None
    risk: str
    input_preview: str | dict | None = None


class MemoryProposal(BaseModel):
    proposal_id: str
    content: str
    memory_type: str


class StepRead(BaseModel):
    step_number: int
    step_type: str
    tool_name: str | None = None
    status: str
    summary: str | None = None
    duration_ms: int | None = None
    created_at: datetime | None = None


class ExecutionRead(BaseModel):
    id: uuid.UUID
    clone_id: uuid.UUID
    status: str
    goal: str
    current_step: int
    total_steps: int
    tool_calls: int
    result_summary: str | None = None
    error: str | None = None
    requires_confirmation: bool
    pending_action: PendingAction | None = None
    memory_proposal: MemoryProposal | None = None
    steps: list[StepRead] = []
    conversation_id: uuid.UUID | None = None
    final_message_id: uuid.UUID | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None


class ExecutionSummary(BaseModel):
    id: uuid.UUID
    status: str
    goal: str  # first 200 characters
    total_steps: int
    created_at: datetime | None
    completed_at: datetime | None
    source: str


class ExecutionPage(BaseModel):
    items: list[ExecutionSummary]
    page: int
    limit: int
    total: int


class ConfirmRequest(_Strict):
    action_id: str = Field(min_length=1, max_length=100)


class MemoryProposalDecision(_Strict):
    proposal_id: str = Field(min_length=1, max_length=100)
    save: bool


# --- Analytics ------------------------------------------------------------------------


class AgentToolStat(BaseModel):
    tool: str
    calls: int
    failures: int
    failure_rate: float


class AgentAnalytics(BaseModel):
    range: str
    executions: int
    completed: int
    failed: int
    cancelled: int
    timeout: int
    avg_duration_ms: int | None
    avg_steps: float
    tools: list[AgentToolStat]
