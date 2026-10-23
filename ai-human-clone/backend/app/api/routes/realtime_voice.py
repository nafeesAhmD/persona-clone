"""Real-time voice (Phase 17): settings, sessions and the session WebSocket.

Settings: anyone who may chat with the clone can read them; only the owner changes
them (get_managed_clone). Sessions follow the chat rules (get_chat_clone) and are
only ever visible to the user who started them. Visitors use their public chat token
(X-Public-Session). The WebSocket needs the one-time ticket returned on creation.
"""

import uuid

from fastapi import APIRouter, Query, Request, WebSocket, status

from app.api.deps import CurrentUser, DbSession
from app.api.routes.public import SessionHeader, _visitor
from app.realtime_voice import connection, service
from app.realtime_voice.schemas import (
    RealtimeSettings,
    RealtimeSettingsUpdate,
    SessionCreate,
    SessionCreated,
    SessionStatus,
)
from app.services import clone_service, public_service

router = APIRouter(tags=["realtime voice"])
# Outside the maintenance guard (a dependency for HTTP requests): the socket checks it itself.
ws_router = APIRouter(tags=["realtime voice"])


@router.get("/clones/{clone_id}/realtime/settings", response_model=RealtimeSettings)
def realtime_settings(clone_id: uuid.UUID, user: CurrentUser, db: DbSession) -> RealtimeSettings:
    return service.settings_of(clone_service.get_chat_clone(db, clone_id, user))


@router.patch("/clones/{clone_id}/realtime/settings", response_model=RealtimeSettings)
def update_realtime_settings(
    clone_id: uuid.UUID, data: RealtimeSettingsUpdate, user: CurrentUser, db: DbSession
) -> RealtimeSettings:
    return service.update_settings(db, clone_service.get_managed_clone(db, clone_id, user), data)


@router.post("/clones/{clone_id}/realtime/session", response_model=SessionCreated, status_code=status.HTTP_201_CREATED)
def create_session(
    clone_id: uuid.UUID, user: CurrentUser, db: DbSession, data: SessionCreate | None = None
) -> SessionCreated:
    clone = clone_service.get_chat_clone(db, clone_id, user)
    return service.create_session(db, clone, user, data or SessionCreate())


@router.get("/clones/{clone_id}/realtime/session/{session_id}", response_model=SessionStatus)
def get_session(clone_id: uuid.UUID, session_id: uuid.UUID, user: CurrentUser, db: DbSession) -> SessionStatus:
    return service.get_session(db, clone_id, session_id, user)


@router.post("/clones/{clone_id}/realtime/session/{session_id}/end", response_model=SessionStatus)
def end_session(clone_id: uuid.UUID, session_id: uuid.UUID, user: CurrentUser, db: DbSession) -> SessionStatus:
    return service.end_session(db, clone_id, session_id, user)


@router.post(
    "/public/clones/{slug}/realtime/session", response_model=SessionCreated, status_code=status.HTTP_201_CREATED
)
def create_public_session(
    slug: str, request: Request, db: DbSession, x_public_session: str | None = SessionHeader
) -> SessionCreated:
    clone = public_service.get_public_clone(db, slug)
    return service.create_public_session(db, clone, x_public_session, _visitor(request).address)


@router.post("/public/clones/{slug}/realtime/session/{session_id}/end", response_model=SessionStatus)
def end_public_session(
    slug: str, session_id: uuid.UUID, db: DbSession, x_public_session: str | None = SessionHeader
) -> SessionStatus:
    clone = public_service.get_public_clone(db, slug)
    return service.end_public_session(db, clone, session_id, x_public_session)


@ws_router.websocket("/realtime/sessions/{session_id}/ws")
async def session_socket(
    websocket: WebSocket, session_id: uuid.UUID, ticket: str | None = Query(default=None, max_length=100)
) -> None:
    await connection.serve(websocket, session_id, ticket)
