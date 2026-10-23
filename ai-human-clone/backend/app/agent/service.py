"""Agent operations used by the API routes (app/api/routes/agent.py, app/api/v1/agent.py).

Contract — the engine work implements these; the API work calls them. Access checks
(who may configure/run) happen in app/agent/access.py BEFORE these are called.

- get_or_create_profile(db, clone) -> AgentProfile            (disabled by default)
- start_execution(db, clone, profile, *, requester, acting_user, goal, source,
                  conversation_id=None, api_key_id=None, input_mode="text") -> AgentExecution
      validates AGENT_ENABLED, profile.enabled, plan limit agent_executions, goal length;
      creates the row (status "queued") and calls runner.submit().
- get_execution(db, execution_id) -> AgentExecution            (no access check here)
- cancel(db, execution) -> AgentExecution                      (sets cancel_requested; final status cancelled)
- confirm(db, execution, action_id) -> AgentExecution          (must match pending_action.action_id; single use)
- reject(db, execution, action_id) -> AgentExecution
- decide_memory_proposal(db, execution, proposal_id, save, user) -> AgentExecution
      save=True creates the memory through the Phase 6 memory service (never auto-approved
      without this explicit user action); cleared either way.
- to_read(db, execution) -> dict matching the API's ExecutionRead (see docs/phase16/contract.md)

Errors: AgentDisabledError (platform or clone agent off), ApiError(429, "usage_limit_reached")
(monthly plan limit "agent_executions"), InvalidInputError (goal length, unsafe memory),
NotFoundError (someone else's conversation), ConfirmationError (wrong/stale/replayed
action or proposal id), ForbiddenError (only the clone owner saves memories).
"""

import hmac
import uuid
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agent import runner, safety
from app.agent.exceptions import AgentDisabledError, ConfirmationError
from app.core.config import get_settings
from app.developer import limits
from app.models import CloneProfile, User
from app.models.agent import FINAL_STATUSES, AgentExecution, AgentProfile, AgentStep
from app.schemas.memory import MemoryCreate
from app.services import conversation_service, memory_service, monitoring
from app.services.errors import ConflictError, ForbiddenError, InvalidInputError

GOAL_MAX_CHARS = 4000
PLATFORM_DISABLED = "The AI agent is turned off on this server."
CLONE_DISABLED = "The AI agent is turned off for this clone."
NOT_WAITING = "This action is no longer waiting for confirmation."
WRONG_ACTION = "That confirmation doesn't match the action that is waiting."
NO_PROPOSAL = "This memory suggestion is no longer available."
CANCELLED = "The run was cancelled."

PENDING_FIELDS = ("action_id", "tool", "title", "reason", "risk", "input_preview")


def _now() -> datetime:
    return datetime.now(UTC)


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


# --- Profile ------------------------------------------------------------------------------


def get_or_create_profile(db: Session, clone: CloneProfile) -> AgentProfile:
    profile = db.scalar(select(AgentProfile).where(AgentProfile.clone_id == clone.id))
    if profile is not None:
        return profile
    settings = get_settings()
    profile = AgentProfile(
        clone_id=clone.id,
        owner_id=clone.owner_id,
        enabled=False,
        max_steps=_clamp(settings.agent_max_steps, 1, 50),
        max_execution_time_seconds=_clamp(settings.agent_max_execution_time_seconds, 5, 600),
        require_confirmation_for_actions=settings.agent_default_confirmation_required,
    )
    db.add(profile)
    try:
        db.commit()
    except IntegrityError:  # created by a concurrent request
        db.rollback()
        return db.scalar(select(AgentProfile).where(AgentProfile.clone_id == clone.id))
    db.refresh(profile)
    return profile


# --- Starting a run -------------------------------------------------------------------------


def monthly_executions(db: Session, clone: CloneProfile) -> int:
    """Runs this month on the clone's billing account (its organization, or its owner)."""
    query = (
        select(func.count())
        .select_from(AgentExecution)
        .join(CloneProfile, CloneProfile.id == AgentExecution.clone_id)
        .where(AgentExecution.created_at >= limits.month_start())
    )
    if clone.organization_id:
        query = query.where(CloneProfile.organization_id == clone.organization_id)
    else:
        query = query.where(CloneProfile.owner_id == clone.owner_id, CloneProfile.organization_id.is_(None))
    return db.scalar(query) or 0


def _check_plan_limit(db: Session, clone: CloneProfile) -> None:
    slug = limits.plan_slug(db, user_id=clone.owner_id, organization_id=clone.organization_id)
    limit = int(limits.plan_limits(db, slug).get("agent_executions", 0) or 0)
    if limit <= 0:
        return
    used = monthly_executions(db, clone)
    if used >= limit:
        raise limits._limit_reached(
            "agent_executions", used, limit, user_id=clone.owner_id, organization_id=clone.organization_id
        )


def start_execution(
    db: Session,
    clone: CloneProfile,
    profile: AgentProfile,
    *,
    requester: User | None,
    acting_user: User | None,
    goal: str,
    source: str,
    conversation_id: uuid.UUID | None = None,
    api_key_id: uuid.UUID | None = None,
    input_mode: str = "text",
) -> AgentExecution:
    if not get_settings().agent_enabled:
        raise AgentDisabledError(PLATFORM_DISABLED)
    if not profile.enabled:
        raise AgentDisabledError(CLONE_DISABLED)
    goal = (goal or "").strip()
    if not goal:
        raise InvalidInputError("Describe what the agent should do.")
    if len(goal) > GOAL_MAX_CHARS:
        raise InvalidInputError(f"The goal is too long (at most {GOAL_MAX_CHARS} characters).")
    if source not in ("app", "api", "public"):
        raise InvalidInputError("Unknown source.")
    _check_plan_limit(db, clone)

    conversation = None
    if acting_user is not None and source != "public":
        # 404 for someone else's conversation or another clone's (checked now, not in the worker).
        conversation = conversation_service.get_or_create(
            db, clone, acting_user, conversation_id, source="api" if source == "api" else "app"
        )
        conversation_service.add_message(
            db, conversation, "user", goal, input_mode=input_mode if input_mode in ("text", "voice") else "text"
        )

    execution = AgentExecution(
        agent_id=profile.id,
        clone_id=clone.id,
        user_id=requester.id if requester is not None else None,
        api_key_id=api_key_id,
        conversation_id=conversation.id if conversation is not None else None,
        source=source,
        status="queued",
        goal=goal,
        created_at=_now(),
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)
    runner.submit(execution.id)
    db.refresh(execution)
    return execution


def get_execution(db: Session, execution_id: uuid.UUID) -> AgentExecution | None:
    return db.get(AgentExecution, execution_id)


# --- Cancel / confirm / reject ----------------------------------------------------------------


def _record_cancelled(db: Session, execution: AgentExecution) -> None:
    clone = db.get(CloneProfile, execution.clone_id)
    monitoring.usage(
        "AGENT_EXECUTION",
        status="cancelled",
        user_id=execution.user_id,
        clone_id=execution.clone_id,
        organization_id=clone.organization_id if clone else None,
        api_key_id=execution.api_key_id,
        output_units=execution.current_step,
    )
    monitoring.security(
        "agent_cancelled", "low", user_id=execution.user_id, details={"execution_id": execution.id, "status": "cancelled"}
    )


def _close_waiting_steps(db: Session, execution: AgentExecution, step_type: str, status: str) -> AgentStep | None:
    step = db.scalar(
        select(AgentStep)
        .where(AgentStep.execution_id == execution.id, AgentStep.step_type == step_type, AgentStep.status == "waiting")
        .order_by(AgentStep.step_number.desc())
        .limit(1)
    )
    if step is not None:
        step.status = status
    return step


def cancel(db: Session, execution: AgentExecution) -> AgentExecution:
    db.refresh(execution)
    if execution.status in FINAL_STATUSES:
        return execution
    execution.cancel_requested = True
    if execution.status in ("queued", "waiting_confirmation"):
        # No worker is running it: end it now (a queued run's worker sees the status and skips it).
        _close_waiting_steps(db, execution, "confirmation", "skipped")
        execution.status = "cancelled"
        execution.error_message = CANCELLED
        execution.pending_action = None
        execution.completed_at = _now()
        db.commit()
        _record_cancelled(db, execution)
    else:
        db.commit()  # the running worker stops before its next planner/tool call
    db.refresh(execution)
    return execution


def _take_pending(execution: AgentExecution, action_id: str) -> dict:
    pending = execution.pending_action or {}
    expected = str(pending.get("action_id") or "")
    if execution.status != "waiting_confirmation" or execution.cancel_requested or not expected or pending.get("state"):
        raise ConfirmationError(NOT_WAITING)
    if not hmac.compare_digest(expected.encode(), str(action_id or "").encode()):
        raise ConfirmationError(WRONG_ACTION)
    return pending


def _decide(db: Session, execution: AgentExecution, action_id: str, approved: bool) -> AgentExecution:
    db.refresh(execution)
    pending = _take_pending(execution, action_id)
    step = _close_waiting_steps(db, execution, "confirmation", "succeeded" if approved else "rejected")
    if step is not None:
        step.output_metadata = {
            **(step.output_metadata or {}),
            "summary": f"You {'approved' if approved else 'declined'} {safety.short(pending.get('title'), 80)}",
        }
    # Single use: the id is consumed now; the worker clears the action once it has read it.
    execution.pending_action = {**pending, "state": "approved" if approved else "rejected"}
    execution.status = "queued"
    db.commit()
    monitoring.security(
        "confirmation_approved" if approved else "confirmation_rejected",
        "low",
        user_id=execution.user_id,
        details={"execution_id": execution.id, "tool": pending.get("tool"), "status": "approved" if approved else "rejected"},
    )
    runner.submit(execution.id)
    db.refresh(execution)
    return execution


def confirm(db: Session, execution: AgentExecution, action_id: str) -> AgentExecution:
    return _decide(db, execution, action_id, True)


def reject(db: Session, execution: AgentExecution, action_id: str) -> AgentExecution:
    return _decide(db, execution, action_id, False)


# --- Memory suggestions ---------------------------------------------------------------------


def decide_memory_proposal(
    db: Session, execution: AgentExecution, proposal_id: str, save: bool, user: User
) -> AgentExecution:
    """The user's explicit decision on the agent's memory suggestion.

    save=True stores it through memory_service.create_manual — the Phase 6 path for a
    memory the owner wrote/approved themselves — with the same secret check. Either way
    the suggestion is cleared."""
    db.refresh(execution)
    proposal = execution.memory_proposal or {}
    expected = str(proposal.get("proposal_id") or "")
    if not expected or not hmac.compare_digest(expected.encode(), str(proposal_id or "").encode()):
        raise ConfirmationError(NO_PROPOSAL)
    clone = db.get(CloneProfile, execution.clone_id)
    if save and (clone is None or user.id != clone.owner_id):
        raise ForbiddenError("Only the clone's owner can save memories.")

    execution.memory_proposal = None
    saved = False
    error: InvalidInputError | None = None
    if save:
        content = str(proposal.get("content") or "")
        if safety.looks_sensitive(content):
            error = InvalidInputError(memory_service.SENSITIVE)
        else:
            try:
                data = MemoryCreate(memory_type=proposal.get("memory_type") or "fact", content=content)
            except ValidationError:
                error = InvalidInputError("This memory suggestion can't be saved.")
            else:
                try:
                    memory_service.create_manual(db, clone, user, data)
                    saved = True
                except ConflictError:
                    saved = True  # already remembered
                except InvalidInputError as exc:
                    error = exc
    execution.memory_proposal = None
    step = _close_waiting_steps(db, execution, "memory_proposal", "succeeded" if saved else "rejected")
    if step is not None:
        step.output_metadata = {
            **(step.output_metadata or {}),
            "summary": "Memory saved" if saved else ("Memory not saved" if error is None else "Memory refused"),
        }
    db.commit()
    monitoring.security(
        "agent_memory_decided",
        "low",
        user_id=user.id,
        details={"execution_id": execution.id, "status": "saved" if saved else ("refused" if error else "dismissed")},
    )
    if error is not None:
        raise error
    db.refresh(execution)
    return execution


# --- Read model -----------------------------------------------------------------------------


def to_read(db: Session, execution: AgentExecution) -> dict:
    """ExecutionRead (docs/phase16/contract.md). Steps carry only their public summary."""
    steps = list(
        db.scalars(select(AgentStep).where(AgentStep.execution_id == execution.id).order_by(AgentStep.step_number))
    )
    waiting = execution.status == "waiting_confirmation" and bool(execution.pending_action)
    pending = {key: (execution.pending_action or {}).get(key) for key in PENDING_FIELDS} if waiting else None
    proposal = execution.memory_proposal
    return {
        "id": execution.id,
        "clone_id": execution.clone_id,
        "status": execution.status,
        "goal": execution.goal,
        "current_step": execution.current_step,
        "total_steps": execution.total_steps,
        "tool_calls": execution.tool_calls,
        "result_summary": execution.result_summary,
        "error": execution.error_message,
        "requires_confirmation": waiting,
        "pending_action": pending,
        "memory_proposal": (
            {key: proposal.get(key) for key in ("proposal_id", "content", "memory_type")} if proposal else None
        ),
        "steps": [
            {
                "step_number": step.step_number,
                "step_type": step.step_type,
                "tool_name": step.tool_name,
                "status": step.status,
                "summary": safety.short((step.output_metadata or {}).get("summary"), 200),
                "duration_ms": step.duration_ms,
                "created_at": step.created_at,
            }
            for step in steps
        ],
        "conversation_id": execution.conversation_id,
        "final_message_id": execution.final_message_id,
        "started_at": execution.started_at,
        "completed_at": execution.completed_at,
        "created_at": execution.created_at,
    }
