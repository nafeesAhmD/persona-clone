"""Long-term memories of a clone. Every route is owner-only.

The clone is loaded through get_managed_clone (404 for other users' private
clones, 403 otherwise), and each memory is then looked up within that clone
and that owner, so a memory id from another clone or user is a 404.
"""

import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.memory import (
    ClearMemoriesRequest,
    ClearMemoriesResponse,
    ExtractionResponse,
    MemoryCreate,
    MemoryRead,
    MemoryStatus,
    MemoryType,
    MemoryUpdate,
)
from app.services import clone_service, conversation_service, memory_service
from app.services.errors import InvalidInputError
from app.services.rate_limit import check_chat_rate

router = APIRouter(tags=["memory"])
CONFIRM_REQUIRED = "Deleting all memories needs explicit confirmation (confirm=true)."


@router.post("/clones/{clone_id}/memories", response_model=MemoryRead, status_code=status.HTTP_201_CREATED)
def create_memory(clone_id: uuid.UUID, data: MemoryCreate, user: CurrentUser, db: DbSession) -> MemoryRead:
    """Add a memory yourself. It is approved (and used in chat) right away."""
    clone = clone_service.get_managed_clone(db, clone_id, user)
    return MemoryRead.model_validate(memory_service.create_manual(db, clone, user, data))


@router.get("/clones/{clone_id}/memories", response_model=list[MemoryRead])
def list_memories(
    clone_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    status_filter: MemoryStatus | None = Query(default=None, alias="status"),
    memory_type: MemoryType | None = None,
) -> list[MemoryRead]:
    """This clone's memories, newest first, optionally filtered by status and type."""
    clone = clone_service.get_managed_clone(db, clone_id, user)
    memories = memory_service.list_memories(db, clone, user, status=status_filter, memory_type=memory_type)
    return [MemoryRead.model_validate(m) for m in memories]


@router.delete("/clones/{clone_id}/memories", response_model=ClearMemoriesResponse)
def delete_all_memories(
    clone_id: uuid.UUID, user: CurrentUser, db: DbSession, confirm: bool = False
) -> ClearMemoriesResponse:
    """Delete every memory of this clone (database and vectors). Requires `?confirm=true`.
    Documents, conversations and the clone are not affected."""
    clone = clone_service.get_managed_clone(db, clone_id, user)
    if not confirm:
        raise InvalidInputError(CONFIRM_REQUIRED)
    return ClearMemoriesResponse(deleted=memory_service.clear_memories(db, clone))


@router.post("/clones/{clone_id}/memories/clear", response_model=ClearMemoriesResponse)
def clear_memories(
    clone_id: uuid.UUID, request: ClearMemoriesRequest, user: CurrentUser, db: DbSession
) -> ClearMemoriesResponse:
    """Same as DELETE /memories, with `{"confirm": true}` in the body."""
    clone = clone_service.get_managed_clone(db, clone_id, user)
    if not request.confirm:
        raise InvalidInputError(CONFIRM_REQUIRED)
    return ClearMemoriesResponse(deleted=memory_service.clear_memories(db, clone))


@router.get("/clones/{clone_id}/memories/{memory_id}", response_model=MemoryRead)
def get_memory(clone_id: uuid.UUID, memory_id: uuid.UUID, user: CurrentUser, db: DbSession) -> MemoryRead:
    clone = clone_service.get_managed_clone(db, clone_id, user)
    return MemoryRead.model_validate(memory_service.get_memory(db, clone, user, memory_id))


@router.patch("/clones/{clone_id}/memories/{memory_id}", response_model=MemoryRead)
def update_memory(
    clone_id: uuid.UUID, memory_id: uuid.UUID, data: MemoryUpdate, user: CurrentUser, db: DbSession
) -> MemoryRead:
    """Edit the type, text or status. An approved memory's vector is rebuilt;
    any other status removes it from chat."""
    clone = clone_service.get_managed_clone(db, clone_id, user)
    memory = memory_service.get_memory(db, clone, user, memory_id)
    return MemoryRead.model_validate(memory_service.update_memory(db, memory, data))


@router.delete("/clones/{clone_id}/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memory(clone_id: uuid.UUID, memory_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    clone = clone_service.get_managed_clone(db, clone_id, user)
    memory_service.delete_memory(db, memory_service.get_memory(db, clone, user, memory_id))


@router.post("/clones/{clone_id}/memories/{memory_id}/approve", response_model=MemoryRead)
def approve_memory(clone_id: uuid.UUID, memory_id: uuid.UUID, user: CurrentUser, db: DbSession) -> MemoryRead:
    """candidate -> approved: the clone starts using it."""
    clone = clone_service.get_managed_clone(db, clone_id, user)
    memory = memory_service.get_memory(db, clone, user, memory_id)
    return MemoryRead.model_validate(memory_service.approve(db, memory))


@router.post("/clones/{clone_id}/memories/{memory_id}/reject", response_model=MemoryRead)
def reject_memory(clone_id: uuid.UUID, memory_id: uuid.UUID, user: CurrentUser, db: DbSession) -> MemoryRead:
    """candidate -> rejected: never used, and not suggested again."""
    clone = clone_service.get_managed_clone(db, clone_id, user)
    memory = memory_service.get_memory(db, clone, user, memory_id)
    return MemoryRead.model_validate(memory_service.reject(db, memory))


@router.post("/conversations/{conversation_id}/extract-memories", response_model=ExtractionResponse)
async def extract_memories(conversation_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ExtractionResponse:
    """Ask the AI for memories worth keeping from this conversation.

    Results are stored as *candidates* only; nothing is used until the owner
    approves it. Only the clone's owner, in their own conversation, can do this.
    """
    conversation = conversation_service.get_owned(db, conversation_id, user)
    clone = clone_service.get_managed_clone(db, conversation.clone_id, user)
    check_chat_rate(user.id)
    outcome = await memory_service.extract_from_conversation(db, clone, user, conversation)
    return ExtractionResponse(
        candidates=[MemoryRead.model_validate(m) for m in outcome.candidates],
        skipped=outcome.skipped,
        message=outcome.message,
    )
