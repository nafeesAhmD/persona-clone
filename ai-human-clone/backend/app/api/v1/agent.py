"""The AI agent through the developer API (Phase 16).

- POST /clones/{clone_id}/agent/run (scope agent:run): start a run → 202 {execution_id, status}.
- GET /agent/executions/{execution_id} (scope agent:read): status, steps and the answer.

Runs act as the clone owner (like API chat), are recorded with source "api" and the key's
id, and need the agent turned on (server and clone). A key only sees executions it could
have started: runs of its clones made through the API (the owner's in-app runs stay private).
"""

import uuid

from fastapi import APIRouter, Request, status

from app.agent import service
from app.agent.exceptions import AgentDisabledError, AgentError, AgentLimitError, ConfirmationError, ToolNotFoundError
from app.api.deps import DbSession
from app.api.routes.agent import disabled_reason, execution_read
from app.developer import access, feature_limits
from app.developer.auth import Scoped
from app.developer.errors import ApiError
from app.schemas.agent import AgentRunRequest, AgentRunResponse, ExecutionRead

router = APIRouter(tags=["Agent"])
NOT_FOUND = "Agent execution not found."


def _api_error(exc: AgentError) -> ApiError:
    message = str(exc) or "The AI agent couldn't do that."
    if isinstance(exc, AgentDisabledError):
        return ApiError(403, "permission_denied", message)
    if isinstance(exc, AgentLimitError):
        return ApiError(429, "usage_limit_reached", message)
    if isinstance(exc, ToolNotFoundError):
        return ApiError(404, "resource_not_found", message)
    if isinstance(exc, ConfirmationError):
        return ApiError(409, "invalid_request", message)
    return ApiError(400, "invalid_request", message)


@router.post(
    "/clones/{clone_id}/agent/run",
    response_model=AgentRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start an AI agent run",
)
def run_agent(
    clone_id: uuid.UUID,
    data: AgentRunRequest,
    request: Request,
    principal: Scoped("agent:run"),
    db: DbSession,
) -> AgentRunResponse:
    """Give the clone's agent a goal (≤ 4000 characters). It plans and uses only the tools
    the owner turned on, then answers. Poll GET /api/v1/agent/executions/{execution_id}.
    Scope: `agent:run`. The owner must have turned the agent on; counts toward the plan's
    monthly `agent_executions`."""
    clone = access.get_clone(db, principal, clone_id, for_use=True)
    feature_limits.mark_clone(request, clone)
    owner = access.acting_user(db, clone)
    profile = service.get_or_create_profile(db, clone)
    reason = disabled_reason(profile)
    if reason:
        raise ApiError(403, "permission_denied", reason)
    if data.conversation_id is not None:
        _, conversation_clone = access.get_conversation(db, principal, data.conversation_id)
        if conversation_clone.id != clone.id:
            raise ApiError(404, "resource_not_found", "Conversation not found.")
    try:
        execution = service.start_execution(
            db,
            clone,
            profile,
            requester=owner,
            acting_user=owner,
            goal=data.goal,
            source="api",
            conversation_id=data.conversation_id,
            api_key_id=principal.key_id,
            input_mode=data.input_mode,
        )
    except AgentError as exc:
        raise _api_error(exc) from None
    db.refresh(execution)
    feature_limits.record("API_AGENT", principal, request, clone)
    return AgentRunResponse(execution_id=execution.id, status=execution.status)


@router.get("/agent/executions/{execution_id}", response_model=ExecutionRead, summary="Get an AI agent run")
def get_execution(
    execution_id: uuid.UUID,
    request: Request,
    principal: Scoped("agent:read"),
    db: DbSession,
) -> ExecutionRead:
    """Status, visible steps (short summaries only), the result and `final_message_id` (the
    saved answer, usable with the voice and avatar endpoints). Scope: `agent:read`."""
    execution = service.get_execution(db, execution_id)
    if execution is None or execution.source != "api":
        raise ApiError(404, "resource_not_found", NOT_FOUND)
    try:
        clone = access.get_clone(db, principal, execution.clone_id)
    except ApiError:
        raise ApiError(404, "resource_not_found", NOT_FOUND) from None
    feature_limits.mark_clone(request, clone)
    return execution_read(db, execution)
