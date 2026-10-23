"""AI agent API for logged-in users (Phase 16). Shapes: docs/phase16/contract.md.

Access (app/agent/access.py): clone owner and org owner/admin configure; org editors
run; org viewers run only when the owner allows it; everyone else is refused (404 for
private clones and for other people's executions). Runs act as the clone owner (same
knowledge and memory as the owner's chat, like the developer API) while the execution
records the logged-in requester. There is no public (visitor) agent endpoint.
"""

import dataclasses
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent import access, service, tool_permissions
from app.agent.exceptions import (
    AgentDisabledError,
    AgentError,
    AgentLimitError,
    ConfirmationError,
    ToolInputError,
    ToolNotAllowedError,
    ToolNotFoundError,
)
from app.api.deps import CurrentUser, DbSession
from app.billing.exceptions import UsageLimitError
from app.core.config import get_settings
from app.models import AgentExecution, AgentProfile, CloneProfile, Conversation, User
from app.schemas.agent import (
    AgentLimits,
    AgentProfileRead,
    AgentProfileUpdate,
    AgentRunRequest,
    AgentRunResponse,
    ConfirmRequest,
    ExecutionPage,
    ExecutionRead,
    ExecutionSummary,
    MemoryProposalDecision,
    ToolSettingRead,
    ToolSettingUpdate,
)
from app.services import platform_service
from app.services.errors import ConflictError, ForbiddenError, InvalidInputError, NotFoundError
from app.services.rate_limit import SlidingWindowLimiter

router = APIRouter(tags=["agent"])

PLATFORM_OFF = "The AI agent isn't enabled on this server."
AGENT_OFF = "The AI agent is turned off for this clone."
PUBLIC_AGENT_OWNER_ONLY = "Only the clone's owner can change the public agent setting."
OWNER_DISABLED = "The owner of this AI Clone is disabled."
CONVERSATION_NOT_FOUND = "Conversation not found"
RUN_RATE_PER_MINUTE = 10

# Runs are the most expensive request (several LLM calls each): a small per-user limit.
agent_run_limiter = SlidingWindowLimiter()


# --- Shared helpers (also used by app/api/v1/agent.py) --------------------------------


def disabled_reason(profile: AgentProfile) -> str | None:
    """Why a run can't start right now, or None."""
    if not get_settings().agent_enabled:
        return PLATFORM_OFF
    if not profile.enabled:
        return AGENT_OFF
    return None


def _plain(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def tool_read(setting: Any) -> ToolSettingRead:
    if dataclasses.is_dataclass(setting):
        data = dataclasses.asdict(setting)
    elif hasattr(setting, "model_dump"):
        data = setting.model_dump()
    elif isinstance(setting, dict):
        data = dict(setting)
    else:
        data = dict(vars(setting))
    return ToolSettingRead.model_validate({key: _plain(value) for key, value in data.items()})


def execution_read(db: Session, execution: AgentExecution) -> ExecutionRead:
    """The engine's to_read() filtered through ExecutionRead: only contract fields leave."""
    return ExecutionRead.model_validate(service.to_read(db, execution))


def map_agent_error(exc: AgentError) -> Exception:
    """Engine/tool errors as the app's HTTP errors (safe messages only)."""
    message = str(exc) or "The AI agent couldn't do that."
    if isinstance(exc, AgentDisabledError):
        return ForbiddenError(message if str(exc) else AGENT_OFF)
    if isinstance(exc, AgentLimitError):
        return UsageLimitError({"message": message})
    if isinstance(exc, ToolNotFoundError):
        return NotFoundError(message)
    if isinstance(exc, (ToolNotAllowedError, ToolInputError)):
        return InvalidInputError(message)
    if isinstance(exc, ConfirmationError):
        return ConflictError(message)
    return InvalidInputError(message)


def _profile(db: Session, clone: CloneProfile) -> AgentProfile:
    return service.get_or_create_profile(db, clone)


def _profile_read(db: Session, user: User, clone: CloneProfile, profile: AgentProfile) -> AgentProfileRead:
    settings = get_settings()
    return AgentProfileRead(
        id=profile.id,
        clone_id=clone.id,
        name=profile.name,
        description=profile.description,
        enabled=profile.enabled,
        max_steps=profile.max_steps,
        max_execution_time_seconds=profile.max_execution_time_seconds,
        require_confirmation_for_actions=profile.require_confirmation_for_actions,
        allow_viewer_use=profile.allow_viewer_use,
        public_agent_enabled=bool(clone.public_agent_enabled),
        platform_enabled=settings.agent_enabled,
        can_configure=access.can_configure(db, user, clone),
        can_run=access.can_run(db, user, clone, profile),
        limits=AgentLimits(
            max_steps=settings.agent_max_steps,
            max_execution_time_seconds=settings.agent_max_execution_time_seconds,
            max_tool_calls=settings.agent_max_tool_calls,
        ),
        tools=[tool_read(t) for t in tool_permissions.effective_tools(db, profile)],
    )


def _get_execution(db: Session, user: User, execution_id: uuid.UUID) -> AgentExecution:
    return access.require_execution(db, user, service.get_execution(db, execution_id))


def _require_decide(db: Session, user: User, execution_id: uuid.UUID) -> AgentExecution:
    """Confirm/reject/memory decisions: must see the execution AND be allowed to run."""
    execution = _get_execution(db, user, execution_id)
    clone = db.get(CloneProfile, execution.clone_id)
    profile = db.get(AgentProfile, execution.agent_id)
    if clone is None or not access.can_run(db, user, clone, profile):
        raise ForbiddenError(access.RUN_DENIED)
    return execution


# --- Profile and tools -----------------------------------------------------------------


@router.get("/clones/{clone_id}/agent", response_model=AgentProfileRead, summary="Get the clone's AI agent")
def get_agent(clone_id: uuid.UUID, user: CurrentUser, db: DbSession) -> AgentProfileRead:
    """The agent's settings, its tools and what you may do with it (`can_configure`, `can_run`).
    The agent is created on first read, turned off."""
    clone = access.require_view(db, user, clone_id)
    return _profile_read(db, user, clone, _profile(db, clone))


@router.patch("/clones/{clone_id}/agent", response_model=AgentProfileRead, summary="Change the AI agent's settings")
def update_agent(clone_id: uuid.UUID, data: AgentProfileUpdate, user: CurrentUser, db: DbSession) -> AgentProfileRead:
    """Owner or organization owner/admin. `public_agent_enabled` only by the clone owner."""
    clone = access.require_configure(db, user, clone_id)
    settings = get_settings()
    changes = data.model_dump(exclude_unset=True)
    if changes.get("max_steps") is not None and not 1 <= changes["max_steps"] <= settings.agent_max_steps:
        raise InvalidInputError(f"max_steps must be between 1 and {settings.agent_max_steps}.")
    limit = settings.agent_max_execution_time_seconds
    seconds = changes.get("max_execution_time_seconds")
    if seconds is not None and not 5 <= seconds <= limit:
        raise InvalidInputError(f"max_execution_time_seconds must be between 5 and {limit}.")
    if "public_agent_enabled" in changes:
        public = changes.pop("public_agent_enabled")
        if public is not None and public != bool(clone.public_agent_enabled):
            if clone.owner_id != user.id:
                raise ForbiddenError(PUBLIC_AGENT_OWNER_ONLY)
            clone.public_agent_enabled = public
    profile = _profile(db, clone)
    for field, value in changes.items():
        if value is None and field != "description":
            continue  # null = leave unchanged
        setattr(profile, field, value)
    db.commit()
    db.refresh(profile)
    return _profile_read(db, user, clone, profile)


@router.put(
    "/clones/{clone_id}/agent/tools/{tool_name}", response_model=ToolSettingRead, summary="Turn one agent tool on or off"
)
def update_tool(
    clone_id: uuid.UUID, tool_name: str, data: ToolSettingUpdate, user: CurrentUser, db: DbSession
) -> ToolSettingRead:
    """Unknown tools are 404; turning on a tool this server can't offer (e.g. web search
    without AGENT_WEB_SEARCH_ENABLED) is 400."""
    clone = access.require_configure(db, user, clone_id)
    profile = _profile(db, clone)
    require_confirmation = data.require_confirmation
    try:
        if require_confirmation is None:
            current = next((t for t in map(tool_read, tool_permissions.effective_tools(db, profile))
                            if t.name == tool_name), None)
            if current is None:
                raise ToolNotFoundError("Unknown tool.")
            require_confirmation = current.require_confirmation
        setting = tool_permissions.set_tool(db, profile, tool_name, data.enabled, require_confirmation)
    except AgentError as exc:
        db.rollback()
        raise map_agent_error(exc) from None
    return tool_read(setting)


# --- Runs ------------------------------------------------------------------------------


@router.post(
    "/clones/{clone_id}/agent/run",
    response_model=AgentRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start an agent run",
)
def run_agent(clone_id: uuid.UUID, data: AgentRunRequest, user: CurrentUser, db: DbSession) -> AgentRunResponse:
    """Starts the run in the background; poll GET /api/agent/executions/{id}."""
    clone, profile = access.require_run(db, user, clone_id, lambda c: _profile(db, c))
    if clone.status == "disabled":
        raise ForbiddenError("This AI Clone is currently disabled.")
    reason = disabled_reason(profile)
    if reason:
        raise ForbiddenError(reason)
    agent_run_limiter.check(
        str(user.id),
        platform_service.rate_limit("agent", RUN_RATE_PER_MINUTE),
        "You're starting agent runs too quickly. Please wait a moment.",
    )
    owner = db.get(User, clone.owner_id)
    if owner is None or not owner.is_active:
        raise ForbiddenError(OWNER_DISABLED)
    if data.conversation_id is not None:
        conversation = db.get(Conversation, data.conversation_id)
        # Only one of your own conversations with this clone.
        if conversation is None or conversation.clone_id != clone.id or conversation.user_id != user.id:
            raise NotFoundError(CONVERSATION_NOT_FOUND)
    try:
        execution = service.start_execution(
            db,
            clone,
            profile,
            requester=user,
            acting_user=owner,
            goal=data.goal,
            source="app",
            conversation_id=data.conversation_id,
            input_mode=data.input_mode,
        )
    except AgentError as exc:
        raise map_agent_error(exc) from None
    db.refresh(execution)
    return AgentRunResponse(execution_id=execution.id, status=execution.status)


@router.get("/clones/{clone_id}/agent/executions", response_model=ExecutionPage, summary="List agent runs")
def list_executions(
    clone_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ExecutionPage:
    """Newest first. Owners and org admins see every run; other members only their own."""
    clone = access.require_view(db, user, clone_id)
    condition = AgentExecution.clone_id == clone.id
    if not access.can_configure(db, user, clone):
        condition = condition & (AgentExecution.user_id == user.id)
    total = db.scalar(select(func.count()).select_from(AgentExecution).where(condition)) or 0
    rows = db.scalars(
        select(AgentExecution)
        .where(condition)
        .order_by(AgentExecution.created_at.desc(), AgentExecution.id)
        .offset((page - 1) * limit)
        .limit(limit)
    )
    items = [
        ExecutionSummary(
            id=e.id, status=e.status, goal=(e.goal or "")[:200], total_steps=e.total_steps,
            created_at=e.created_at, completed_at=e.completed_at, source=e.source,
        )
        for e in rows
    ]
    return ExecutionPage(items=items, page=page, limit=limit, total=total)


@router.get("/agent/executions/{execution_id}", response_model=ExecutionRead, summary="Get an agent run")
def get_execution(execution_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ExecutionRead:
    """Status, visible steps (short summaries, never hidden reasoning), any action waiting
    for your confirmation and the final answer's message id."""
    return execution_read(db, _get_execution(db, user, execution_id))


@router.post("/agent/executions/{execution_id}/cancel", response_model=ExecutionRead, summary="Cancel an agent run")
def cancel_execution(execution_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ExecutionRead:
    execution = _get_execution(db, user, execution_id)
    try:
        execution = service.cancel(db, execution)
    except AgentError as exc:
        raise map_agent_error(exc) from None
    return execution_read(db, execution)


@router.post("/agent/executions/{execution_id}/confirm", response_model=ExecutionRead, summary="Approve a pending action")
def confirm_action(execution_id: uuid.UUID, data: ConfirmRequest, user: CurrentUser, db: DbSession) -> ExecutionRead:
    """`action_id` must match the pending action (single use); otherwise 409."""
    execution = _require_decide(db, user, execution_id)
    try:
        execution = service.confirm(db, execution, data.action_id)
    except AgentError as exc:
        raise map_agent_error(exc) from None
    return execution_read(db, execution)


@router.post("/agent/executions/{execution_id}/reject", response_model=ExecutionRead, summary="Reject a pending action")
def reject_action(execution_id: uuid.UUID, data: ConfirmRequest, user: CurrentUser, db: DbSession) -> ExecutionRead:
    execution = _require_decide(db, user, execution_id)
    try:
        execution = service.reject(db, execution, data.action_id)
    except AgentError as exc:
        raise map_agent_error(exc) from None
    return execution_read(db, execution)


@router.post(
    "/agent/executions/{execution_id}/memory-proposal",
    response_model=ExecutionRead,
    summary="Save or dismiss a suggested memory",
)
def decide_memory(
    execution_id: uuid.UUID, data: MemoryProposalDecision, user: CurrentUser, db: DbSession
) -> ExecutionRead:
    """The agent never saves memories by itself: `save: true` stores the suggestion (clone
    owner only, since memories are the owner's); anyone who may run can dismiss it."""
    execution = _require_decide(db, user, execution_id)
    try:
        execution = service.decide_memory_proposal(db, execution, data.proposal_id, data.save, user)
    except AgentError as exc:
        raise map_agent_error(exc) from None
    return execution_read(db, execution)
