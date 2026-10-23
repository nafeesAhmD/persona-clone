"""Organization memory management - allows editors to manage memories for org clones.

Memories stay owned by the clone's owner (that is whose memories the clone uses in
chat), so every change goes through memory_service with the clone owner as the user;
this keeps the vector store in step exactly like the owner's own routes.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.clone_profile import CloneProfile
from app.org.authz.permissions import has_clone_role
from app.schemas.memory import MemoryCreate, MemoryRead, MemoryStatus, MemoryUpdate
from app.services import memory_service

router = APIRouter(prefix="/organizations/{organization_id}/clones/{clone_id}", tags=["organizations-memory"])

READERS = {"owner", "admin", "editor", "viewer"}
EDITORS = {"owner", "admin", "editor"}
APPROVERS = {"owner", "admin"}


def _org_clone(db, user_id: uuid.UUID, organization_id: uuid.UUID, clone_id: uuid.UUID, roles: set[str]) -> CloneProfile:
    """The clone, if it belongs to this organization and the user's role allows `roles`."""
    clone = db.query(CloneProfile).filter(CloneProfile.id == clone_id).first()
    if not clone:
        raise HTTPException(status_code=404, detail="not_found")
    ok, _ = has_clone_role(db, user_id, clone_id, roles)
    if not ok:
        raise HTTPException(status_code=403, detail="forbidden")
    if clone.organization_id != organization_id:
        raise HTTPException(status_code=400, detail="clone_not_in_org")
    return clone


@router.post("/memories", response_model=MemoryRead, status_code=201)
def org_create_memory(
    organization_id: uuid.UUID,
    clone_id: uuid.UUID,
    data: MemoryCreate,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Create a memory for an organization clone (editor/admin/owner). Approved right away."""
    clone = _org_clone(db, current_user.id, organization_id, clone_id, EDITORS)
    return MemoryRead.model_validate(memory_service.create_manual(db, clone, clone.owner, data))


@router.get("/memories", response_model=list[MemoryRead])
def org_list_memories(
    organization_id: uuid.UUID,
    clone_id: uuid.UUID,
    status_filter: MemoryStatus | None = Query(default=None, alias="status"),
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """List memories for an organization clone (any member)."""
    clone = _org_clone(db, current_user.id, organization_id, clone_id, READERS)
    memories = memory_service.list_memories(db, clone, clone.owner, status=status_filter)
    return [MemoryRead.model_validate(m) for m in memories]


@router.get("/memories/{memory_id}", response_model=MemoryRead)
def org_get_memory(
    organization_id: uuid.UUID,
    clone_id: uuid.UUID,
    memory_id: uuid.UUID,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    clone = _org_clone(db, current_user.id, organization_id, clone_id, READERS)
    return MemoryRead.model_validate(memory_service.get_memory(db, clone, clone.owner, memory_id))


@router.patch("/memories/{memory_id}", response_model=MemoryRead)
def org_update_memory(
    organization_id: uuid.UUID,
    clone_id: uuid.UUID,
    memory_id: uuid.UUID,
    data: MemoryUpdate,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Update a memory (editor/admin/owner)."""
    clone = _org_clone(db, current_user.id, organization_id, clone_id, EDITORS)
    memory = memory_service.get_memory(db, clone, clone.owner, memory_id)
    return MemoryRead.model_validate(memory_service.update_memory(db, memory, data))


@router.delete("/memories/{memory_id}", status_code=204)
def org_delete_memory(
    organization_id: uuid.UUID,
    clone_id: uuid.UUID,
    memory_id: uuid.UUID,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Delete a memory (editor/admin/owner)."""
    clone = _org_clone(db, current_user.id, organization_id, clone_id, EDITORS)
    memory_service.delete_memory(db, memory_service.get_memory(db, clone, clone.owner, memory_id))


@router.post("/memories/{memory_id}/approve", response_model=MemoryRead)
def org_approve_memory(
    organization_id: uuid.UUID,
    clone_id: uuid.UUID,
    memory_id: uuid.UUID,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Approve a memory for AI use (admin/owner)."""
    clone = _org_clone(db, current_user.id, organization_id, clone_id, APPROVERS)
    memory = memory_service.get_memory(db, clone, clone.owner, memory_id)
    return MemoryRead.model_validate(memory_service.approve(db, memory))
