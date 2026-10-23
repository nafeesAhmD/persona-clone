"""Live video calls with a clone's avatar (Simli). See app/avatar/live_avatar.py.

Face setup is owner only (get_managed_clone). Calls follow the chat rules
(get_chat_clone): the owner, or a logged-in user when the owner made the clone
public with public avatars on. The Simli API key never leaves the server.
"""

import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DbSession
from app.avatar import live_avatar
from app.schemas.avatar import LiveAvatarStatus, LiveCallAvailability, LiveCallEnd, LiveCallStart, LiveFaceIdUpdate
from app.services import clone_service

router = APIRouter(prefix="/clones/{clone_id}", tags=["live avatar"])


@router.get("/live-avatar", response_model=LiveAvatarStatus)
def live_avatar_status(clone_id: uuid.UUID, user: CurrentUser, db: DbSession) -> LiveAvatarStatus:
    clone = clone_service.get_managed_clone(db, clone_id, user)
    return LiveAvatarStatus(**live_avatar.refresh_face(db, clone))


@router.post("/live-avatar/face", response_model=LiveAvatarStatus)
def create_live_face(clone_id: uuid.UUID, user: CurrentUser, db: DbSession) -> LiveAvatarStatus:
    """Send the active avatar photo to Simli to build the live face (once)."""
    clone = clone_service.get_managed_clone(db, clone_id, user)
    return LiveAvatarStatus(**live_avatar.create_face(db, clone))


@router.put("/live-avatar/face-id", response_model=LiveAvatarStatus)
def set_live_face_id(clone_id: uuid.UUID, data: LiveFaceIdUpdate, user: CurrentUser, db: DbSession) -> LiveAvatarStatus:
    """Use a face already made in the Simli app."""
    clone = clone_service.get_managed_clone(db, clone_id, user)
    return LiveAvatarStatus(**live_avatar.set_face_id(db, clone, data.face_id))


@router.get("/live-call", response_model=LiveCallAvailability)
def live_call_availability(clone_id: uuid.UUID, user: CurrentUser, db: DbSession) -> LiveCallAvailability:
    clone = clone_service.get_chat_clone(db, clone_id, user)
    problem = live_avatar.call_problem(clone, user)
    return LiveCallAvailability(can_call=problem is None, reason=problem)


@router.post("/live-call", response_model=LiveCallStart, status_code=status.HTTP_201_CREATED)
def start_live_call(clone_id: uuid.UUID, user: CurrentUser, db: DbSession) -> LiveCallStart:
    clone = clone_service.get_chat_clone(db, clone_id, user)
    call = live_avatar.start_call(clone, user)
    return LiveCallStart(
        session_token=call.session_token,
        ice_servers=call.ice_servers,
        max_seconds=call.max_seconds,
        max_idle_seconds=call.max_idle_seconds,
    )


@router.post("/live-call/end", status_code=status.HTTP_204_NO_CONTENT)
def end_live_call(clone_id: uuid.UUID, data: LiveCallEnd, user: CurrentUser, db: DbSession) -> None:
    clone = clone_service.get_chat_clone(db, clone_id, user)
    live_avatar.record_call_end(clone, user, data.seconds)
