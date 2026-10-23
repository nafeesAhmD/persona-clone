"""Which clones and conversations an API key may use.

- Personal key: the clones its user owns.
- Organization key: the clones assigned to its organization (CloneProfile.organization_id).
API calls run as the clone's owner account (same prompt, knowledge and memory as the
owner's own chat), so conversations created through the API belong to that account.
Anything else is "not found", so a key can't discover other people's clones.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.developer.auth import ApiPrincipal
from app.developer.errors import ApiError
from app.models import CloneProfile, Conversation, User

NOT_FOUND = "AI Clone not found."


def _scope(principal: ApiPrincipal):
    if principal.organization_id is not None:
        return CloneProfile.organization_id == principal.organization_id
    return CloneProfile.owner_id == principal.user_id


def list_clones(db: Session, principal: ApiPrincipal) -> list[CloneProfile]:
    return list(db.scalars(select(CloneProfile).where(_scope(principal)).order_by(CloneProfile.created_at.desc())))


def get_clone(db: Session, principal: ApiPrincipal, clone_id: uuid.UUID, *, for_use: bool = False) -> CloneProfile:
    """The clone if this key may access it (404 otherwise). `for_use`: also active."""
    clone = db.scalar(select(CloneProfile).where(CloneProfile.id == clone_id, _scope(principal)))
    if clone is None:
        raise ApiError(404, "resource_not_found", NOT_FOUND)
    if for_use and clone.status == "disabled":
        raise ApiError(403, "permission_denied", "This AI Clone is disabled.")
    return clone


def acting_user(db: Session, clone: CloneProfile) -> User:
    owner = db.get(User, clone.owner_id)
    if owner is None or not owner.is_active:
        raise ApiError(403, "permission_denied", "The owner of this AI Clone is disabled.")
    return owner


def get_conversation(db: Session, principal: ApiPrincipal, conversation_id: uuid.UUID) -> tuple[Conversation, CloneProfile]:
    conversation = db.get(Conversation, conversation_id)
    if conversation is not None:
        clone = db.scalar(select(CloneProfile).where(CloneProfile.id == conversation.clone_id, _scope(principal)))
        # Only conversations started through the API: the owner's own app chats stay private.
        if clone is not None and conversation.user_id == clone.owner_id and conversation.source == "api":
            return conversation, clone
    raise ApiError(404, "resource_not_found", "Conversation not found.")
