"""POST /api/v1/clones/{clone_id}/chat (scope clone:chat).

Runs the same chat turn as the owner's own chat (chat_service.chat: knowledge + approved
memories + LLM, both messages saved) as the clone's owner account, so the API never
duplicates the RAG pipeline. Before the turn: the clone must be accessible and active,
the plan's monthly chat messages must not be used up, and a given conversation_id must
belong to this clone and its owner (404 otherwise). Sources carry titles and scores
only, never document text.
"""

import time
import uuid

from fastapi import APIRouter, Request

from app.api.deps import DbSession
from app.developer import access, feature_limits, limits
from app.developer.auth import Scoped
from app.developer.errors import ApiError
from app.schemas.api_v1 import ApiChatRequest, ApiChatResponse, ApiSource
from app.schemas.chat import ChatRequest
from app.services import chat_service

router = APIRouter(tags=["Chat"])


@router.post("/clones/{clone_id}/chat", response_model=ApiChatResponse, summary="Chat with an AI Clone")
async def chat(
    clone_id: uuid.UUID, data: ApiChatRequest, request: Request, principal: Scoped("clone:chat"), db: DbSession
) -> ApiChatResponse:
    """Send a message and get the clone's answer, grounded in its knowledge.

    Pass `conversation_id` from a previous response to continue that conversation.
    Scope: `clone:chat`. Counts toward the plan's monthly chat messages.
    """
    clone = access.get_clone(db, principal, clone_id, for_use=True)
    feature_limits.mark_clone(request, clone)
    owner = access.acting_user(db, clone)
    if data.conversation_id is not None:
        conversation, conversation_clone = access.get_conversation(db, principal, data.conversation_id)
        if conversation_clone.id != clone.id:
            raise ApiError(404, "resource_not_found", "Conversation not found.")
    limits.check_chat_messages(
        db, acting_user_id=owner.id, user_id=principal.user_id, organization_id=principal.organization_id
    )

    started = time.monotonic()
    try:
        reply = await chat_service.chat(
            db, clone, owner, ChatRequest(message=data.message, conversation_id=data.conversation_id), source="api"
        )
    except Exception:
        feature_limits.record("API_CHAT", principal, request, clone, status="error",
                              duration_ms=int((time.monotonic() - started) * 1000))
        raise
    feature_limits.record("API_CHAT", principal, request, clone, duration_ms=int((time.monotonic() - started) * 1000))
    return ApiChatResponse(
        conversation_id=reply.conversation_id,
        message_id=reply.message.id,
        message=reply.message.content,
        sources=[ApiSource(title=source.title, score=round(source.score, 4)) for source in reply.sources],
        memories_used=reply.memories_used,
        created_at=reply.message.created_at,
    )
