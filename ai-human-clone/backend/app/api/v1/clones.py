"""GET /api/v1/clones and /api/v1/clones/{clone_id} (scope clone:read).

A personal key sees the clones its user owns; an organization key the clones assigned
to its organization. Any other clone is 404, so keys can't discover other people's
clones. Only public profile fields are returned (app/schemas/api_v1.ApiClone): never the
system prompt, personality or communication-style text, or memory.
"""

import uuid

from fastapi import APIRouter, Request

from app.api.deps import DbSession
from app.developer import access, feature_limits
from app.developer.auth import Scoped
from app.schemas.api_v1 import ApiClone, ApiCloneList

router = APIRouter(tags=["Clones"])


@router.get("/clones", response_model=ApiCloneList, summary="List AI Clones")
def list_clones(principal: Scoped("clone:read"), db: DbSession) -> ApiCloneList:
    """The AI Clones this key can use, newest first. Scope: `clone:read`."""
    return ApiCloneList(data=[ApiClone.model_validate(clone) for clone in access.list_clones(db, principal)])


@router.get("/clones/{clone_id}", response_model=ApiClone, summary="Get an AI Clone")
def get_clone(clone_id: uuid.UUID, request: Request, principal: Scoped("clone:read"), db: DbSession) -> ApiClone:
    """One AI Clone's public profile. Scope: `clone:read`. 404 if the key can't access it."""
    clone = access.get_clone(db, principal, clone_id)
    feature_limits.mark_clone(request, clone)
    return ApiClone.model_validate(clone)
