import uuid

from fastapi import APIRouter, status
from sqlalchemy.orm import Session

from app.ai import public_rag_pipeline
from app.api.deps import CurrentUser, DbSession
from app.models import CloneProfile
from app.schemas.clone import CloneChatProfile, CloneCreate, CloneResponse, CloneSummary, CloneUpdate
from app.services import clone_service, ingestion_service

PUBLIC_LIST_LIMIT = 200

router = APIRouter(prefix="/clones", tags=["clones"])


# --- Management (owner only) ------------------------------------------------


@router.post("", response_model=CloneResponse, status_code=status.HTTP_201_CREATED)
def create_clone(data: CloneCreate, user: CurrentUser, db: DbSession) -> CloneResponse:
    """Create a clone. The owner is always the logged-in user; owner_id can't be sent."""
    return CloneResponse.model_validate(clone_service.create_clone(db, data, owner=user))


def _with_stats(db: Session, clones: list[CloneProfile], schema: type[CloneSummary]) -> list:
    stats = ingestion_service.knowledge_stats(db, [c.id for c in clones])
    return [schema.model_validate(c).model_copy(update=stats.get(c.id, {})) for c in clones]


@router.get("", response_model=list[CloneSummary])
def list_my_clones(user: CurrentUser, db: DbSession) -> list[CloneSummary]:
    """Only the logged-in user's clones."""
    return _with_stats(db, clone_service.list_owned_clones(db, user), CloneSummary)


@router.get("/public", response_model=list[CloneSummary])
def list_public_clones(db: DbSession) -> list[CloneSummary]:
    """Clones whose owners made them public and active (newest first, at most
    PUBLIC_LIST_LIMIT). Knowledge counts stay 0 here: they would count the owner's
    private documents too, which is nobody else's business."""
    return [CloneSummary.model_validate(c) for c in clone_service.list_public_clones(db, PUBLIC_LIST_LIMIT)]


@router.get("/{clone_id}", response_model=CloneResponse)
def get_clone(clone_id: uuid.UUID, user: CurrentUser, db: DbSession) -> CloneResponse:
    return _with_stats(db, [clone_service.get_managed_clone(db, clone_id, user)], CloneResponse)[0]


@router.patch("/{clone_id}", response_model=CloneResponse)
def update_clone(clone_id: uuid.UUID, data: CloneUpdate, user: CurrentUser, db: DbSession) -> CloneResponse:
    clone = clone_service.get_managed_clone(db, clone_id, user)
    return _with_stats(db, [clone_service.update_clone(db, clone, data)], CloneResponse)[0]


@router.delete("/{clone_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_clone(clone_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    clone_service.delete_clone(db, clone_service.get_managed_clone(db, clone_id, user))


# --- Chat screen info (anyone allowed to chat; see clone_service.get_chat_clone) --


@router.get("/{clone_id}/chat-profile", response_model=CloneChatProfile)
def get_chat_profile(clone_id: uuid.UUID, user: CurrentUser, db: DbSession) -> CloneChatProfile:
    """The clone info a chat screen needs, without private settings."""
    clone = clone_service.get_chat_clone(db, clone_id, user)
    is_owner = clone.owner_id == user.id
    if is_owner:
        has_knowledge = bool(ingestion_service.knowledge_stats(db, [clone.id]).get(clone.id, {}).get("indexed_count"))
    else:  # visitors only ever get public content
        has_knowledge = bool(public_rag_pipeline.public_scope(db, clone).document_ids)
    return CloneChatProfile.model_validate(clone).model_copy(
        update={
            "is_owner": is_owner,
            "has_knowledge": has_knowledge,
            # What this viewer may use: visitors need the owner's public switches.
            "voice_enabled": clone.voice_enabled and (is_owner or clone.public_voice_enabled),
            "avatar_enabled": clone.avatar_enabled and is_owner,
        }
    )
