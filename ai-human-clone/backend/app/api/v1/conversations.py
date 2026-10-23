"""Conversations of a clone through the API.

- GET /api/v1/clones/{clone_id}/conversations (conversation:read)
- GET /api/v1/conversations/{conversation_id} (conversation:read), with its messages
- DELETE /api/v1/conversations/{conversation_id} (conversation:write)

API chats run as the clone's owner, so these are the owner's conversations with that
clone (access.get_conversation checks clone access and ownership). Anything else is 404.
"""

import uuid

from fastapi import APIRouter, Request, status

from app.api.deps import DbSession
from app.developer import access, feature_limits
from app.developer.auth import Scoped
from app.schemas.api_v1 import ApiConversation, ApiConversationDetail, ApiConversationList, ApiMessage
from app.services import conversation_service

router = APIRouter(tags=["Conversations"])


@router.get(
    "/clones/{clone_id}/conversations", response_model=ApiConversationList, summary="List a clone's conversations"
)
def list_conversations(
    clone_id: uuid.UUID, request: Request, principal: Scoped("conversation:read"), db: DbSession
) -> ApiConversationList:
    """The clone owner's conversations with this clone, most recent first. Scope: `conversation:read`."""
    clone = access.get_clone(db, principal, clone_id)
    feature_limits.mark_clone(request, clone)
    owner = access.acting_user(db, clone)
    rows = conversation_service.list_for(db, clone, owner, source="api")
    return ApiConversationList(data=[ApiConversation.model_validate(row) for row in rows])


@router.get("/conversations/{conversation_id}", response_model=ApiConversationDetail, summary="Get a conversation")
def get_conversation(
    conversation_id: uuid.UUID, request: Request, principal: Scoped("conversation:read"), db: DbSession
) -> ApiConversationDetail:
    """A conversation with its messages (role, content, time). Scope: `conversation:read`."""
    conversation, clone = access.get_conversation(db, principal, conversation_id)
    feature_limits.mark_clone(request, clone)
    messages = conversation_service.messages_of(db, conversation)
    return ApiConversationDetail(
        **ApiConversation.model_validate(conversation).model_dump(),
        messages=[ApiMessage.model_validate(message) for message in messages],
    )


@router.delete(
    "/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a conversation"
)
def delete_conversation(
    conversation_id: uuid.UUID, request: Request, principal: Scoped("conversation:write"), db: DbSession
) -> None:
    """Delete a conversation and its messages permanently. Scope: `conversation:write`."""
    conversation, clone = access.get_conversation(db, principal, conversation_id)
    feature_limits.mark_clone(request, clone)
    conversation_service.delete(db, conversation)
