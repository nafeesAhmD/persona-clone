"""Clone chat and conversation history. Every route requires login.

Chat access to a clone: its owner, or any logged-in user when the clone is
public/unlisted and active (clone_service.get_chat_clone). Conversations are
private to the user who had them: other users get 404, clone owners included.
"""

import uuid

from fastapi import APIRouter, status
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser, DbSession
from app.avatar import lip_sync_service
from app.schemas.chat import ChatRequest, ChatResponse, ConversationDetail, ConversationListItem, MessageRead
from app.services import chat_service, clone_service, conversation_service

router = APIRouter(tags=["chat"])


@router.post("/clones/{clone_id}/chat", response_model=ChatResponse)
async def chat_with_clone(clone_id: uuid.UUID, request: ChatRequest, user: CurrentUser, db: DbSession) -> ChatResponse:
    """Ask the clone a question. `conversation_id: null` starts a new conversation."""
    clone = clone_service.get_chat_clone(db, clone_id, user)
    return await chat_service.chat(db, clone, user, request)


@router.post("/clones/{clone_id}/chat/stream")
async def stream_chat_with_clone(
    clone_id: uuid.UUID, request: ChatRequest, user: CurrentUser, db: DbSession
) -> StreamingResponse:
    """Same as /chat, streamed as server-sent events: meta, delta..., then done or error."""
    clone = clone_service.get_chat_clone(db, clone_id, user)
    turn = await chat_service.prepare_stream(db, clone, user, request)
    return StreamingResponse(
        chat_service.stream_chat(turn),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/clones/{clone_id}/conversations", response_model=list[ConversationListItem])
def list_conversations(clone_id: uuid.UUID, user: CurrentUser, db: DbSession) -> list[ConversationListItem]:
    """The current user's conversations with this clone, most recent first."""
    clone = clone_service.get_chat_clone(db, clone_id, user)
    return [ConversationListItem.model_validate(c) for c in conversation_service.list_for(db, clone, user)]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ConversationDetail:
    conversation = conversation_service.get_owned(db, conversation_id, user)
    rows = conversation_service.messages_of(db, conversation)
    videos = lip_sync_service.latest_jobs_for(db, user, [m.id for m in rows if m.role == "assistant"])
    messages = [
        MessageRead.model_validate(m).model_copy(
            update={"avatar_job_id": videos[m.id].id, "avatar_job_status": videos[m.id].status} if m.id in videos else {}
        )
        for m in rows
    ]
    return ConversationDetail.model_validate(conversation).model_copy(update={"messages": messages})


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    conversation_service.delete(db, conversation_service.get_owned(db, conversation_id, user))
