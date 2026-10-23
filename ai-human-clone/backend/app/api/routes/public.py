"""Public clone API for anonymous visitors (no login, no cookies used).

The visitor's session token is sent in the X-Public-Session header (or the chat
body's session_id). Only public profile fields and public content are ever
returned; owner account data, private documents and memories, prompts and
internals never are. See app/services/public_service.py for the access rules.
"""

import uuid

from fastapi import APIRouter, File, Header, Query, Request, UploadFile, status
from fastapi.responses import FileResponse

from app.api.deps import DbSession
from app.avatar.lip_sync_service import video_file
from app.avatar.storage import get_avatar_storage
from app.schemas.public import (
    PublicChatRequest,
    PublicChatResponse,
    PublicClone,
    PublicCloneList,
    PublicJobCreated,
    PublicJobRead,
    PublicMediaResponse,
    PublicMessage,
    PublicSessionRead,
)
from app.schemas.voice import TranscriptionResponse
from app.services import monitoring, public_service, public_session_service
from app.services.public_service import Visitor
from app.voice.audio import max_audio_bytes, too_large_message
from app.voice.base import InvalidAudioError
from app.voice.storage import MIME_TYPES

router = APIRouter(prefix="/public/clones", tags=["public"])
SessionHeader = Header(default=None, alias="X-Public-Session", max_length=200)
_NO_STORE = {"Cache-Control": "no-store", "Vary": "X-Public-Session"}


def _visitor(request: Request) -> Visitor:
    """The client address, for rate limits only. Proxy headers only when trusted."""
    return Visitor(address=monitoring.client_ip(request) or "unknown")


@router.get("", response_model=PublicCloneList)
def discover(
    db: DbSession,
    page: int = Query(default=1, ge=1, le=1000),
    limit: int = Query(default=20, ge=1, le=50),
    search: str | None = Query(default=None, max_length=100),
    profession: str | None = Query(default=None, max_length=100),
    skill: str | None = Query(default=None, max_length=50),
    language: str | None = Query(default=None, max_length=60),
) -> PublicCloneList:
    """Public clones with public chat on (unlisted ones are never listed)."""
    return public_service.discover(
        db, page=page, limit=limit, search=search, profession=profession, skill=skill, language=language
    )


@router.get("/{slug}", response_model=PublicClone)
def get_public_clone(slug: str, db: DbSession) -> PublicClone:
    return public_service.profile(db, public_service.get_public_clone(db, slug))


@router.get("/{slug}/avatar-image", response_class=FileResponse)
def get_avatar_image(slug: str, db: DbSession) -> FileResponse:
    """The clone's avatar picture, only when the owner made avatar replies public."""
    clone = public_service.get_public_clone(db, slug)
    return FileResponse(public_service.avatar_image_file(db, clone), media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/{slug}/chat", response_model=PublicChatResponse)
async def public_chat(
    slug: str, data: PublicChatRequest, request: Request, db: DbSession, session_token: str | None = SessionHeader
) -> PublicChatResponse:
    """Chat with a public clone. Without a session, one is started and its token returned
    as `session_id`; send it back (header or body) to continue the conversation."""
    clone = public_service.get_public_clone(db, slug)
    return await public_service.chat(db, clone, _visitor(request), data, session_token)


@router.get("/{slug}/session", response_model=PublicSessionRead)
def get_session(slug: str, db: DbSession, session_token: str | None = SessionHeader) -> PublicSessionRead:
    """The visitor's conversation so far (to restore it after a reload)."""
    clone = public_service.get_public_clone(db, slug)
    session = public_service.session_for(db, clone, session_token)
    return PublicSessionRead(
        expires_at=public_session_service.aware(session.expires_at),
        messages=[PublicMessage.model_validate(m) for m in public_session_service.messages_of(db, session)],
        messages_left=public_session_service.messages_left(session),
    )


@router.delete("/{slug}/session", status_code=status.HTTP_204_NO_CONTENT)
def end_session(slug: str, db: DbSession, session_token: str | None = SessionHeader) -> None:
    """Clear the conversation: its messages are deleted."""
    clone = public_service.get_public_clone(db, slug)
    session = public_session_service.find(db, clone, session_token)
    if session is not None:
        public_session_service.end(db, session)


@router.post("/{slug}/voice/transcribe", response_model=TranscriptionResponse)
async def transcribe(slug: str, request: Request, db: DbSession, audio: UploadFile = File(...)) -> TranscriptionResponse:
    clone = public_service.get_public_clone(db, slug)
    data = await audio.read(max_audio_bytes() + 1)
    if len(data) > max_audio_bytes():
        raise InvalidAudioError(too_large_message(), status_code=413)
    speech = await public_service.transcribe(clone, _visitor(request), data, audio.filename, audio.content_type)
    return TranscriptionResponse(text=speech.text, language=speech.language, duration_seconds=speech.duration_seconds)


@router.post("/{slug}/messages/{message_id}/speech", response_model=PublicMediaResponse)
async def speak(
    slug: str, message_id: uuid.UUID, request: Request, db: DbSession, session_token: str | None = SessionHeader
) -> PublicMediaResponse:
    clone = public_service.get_public_clone(db, slug)
    return PublicMediaResponse(audio_url=await public_service.speak(db, clone, _visitor(request), session_token, message_id))


@router.get("/{slug}/audio/{audio_id}", response_class=FileResponse)
def get_audio(slug: str, audio_id: str, db: DbSession, session_token: str | None = SessionHeader) -> FileResponse:
    clone = public_service.get_public_clone(db, slug)
    path = public_service.audio_file(db, clone, session_token, audio_id)
    return FileResponse(path, media_type=MIME_TYPES[path.suffix.lstrip(".")], headers=_NO_STORE)


@router.post("/{slug}/messages/{message_id}/avatar", response_model=PublicJobCreated, status_code=status.HTTP_202_ACCEPTED)
def create_avatar_video(
    slug: str, message_id: uuid.UUID, request: Request, db: DbSession, session_token: str | None = SessionHeader
) -> PublicJobCreated:
    clone = public_service.get_public_clone(db, slug)
    job = public_service.create_video(db, clone, _visitor(request), session_token, message_id)
    return PublicJobCreated(job_id=job.id, status=job.status)


@router.get("/{slug}/avatar/jobs/{job_id}", response_model=PublicJobRead)
def get_avatar_job(slug: str, job_id: uuid.UUID, db: DbSession, session_token: str | None = SessionHeader) -> PublicJobRead:
    clone = public_service.get_public_clone(db, slug)
    job = public_service.get_job(db, clone, session_token, job_id)
    fresh = job.status == "completed" and get_avatar_storage().video_if_fresh(clone.id, job.output_video_path)
    return PublicJobRead(
        job_id=job.id,
        status=job.status,
        progress=job.progress,
        video_url=public_service.video_url(clone, job) if fresh else None,
        error_message=job.error_message,
    )


@router.get("/{slug}/avatar/jobs/{job_id}/video", response_class=FileResponse)
def get_avatar_video(slug: str, job_id: uuid.UUID, db: DbSession, session_token: str | None = SessionHeader) -> FileResponse:
    clone = public_service.get_public_clone(db, slug)
    path = video_file(public_service.get_job(db, clone, session_token, job_id))
    return FileResponse(path, media_type="video/mp4", headers=_NO_STORE)
