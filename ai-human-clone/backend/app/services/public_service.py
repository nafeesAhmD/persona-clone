"""Public clones for anonymous visitors: profile, discovery, chat, voice, avatar.

Access rules (checked on every request, so turning things off is immediate):
- The clone is found by slug and must be public or unlisted and active; a
  private, draft or disabled clone is "not found" (its existence isn't revealed).
- Unlisted clones work by exact link but are never listed or searched.
- Chat needs public_chat_enabled; voice also public_voice_enabled; avatar
  videos also public_avatar_enabled (plus the owner's own voice/avatar setup).
- Answers come only from public content (public_rag_pipeline) with the public
  prompt and limits. Visitor data: only the session's messages, nothing else.
"""

import logging
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.ai import public_rag_pipeline
from app.ai.base import LLMError
from app.avatar import avatar_service, jobs
from app.avatar import factory as avatar_factory
from app.core.config import get_settings
from app.models import AvatarVideoJob, CloneProfile, PublicChatSession, User
from app.schemas.public import (
    PublicChatRequest,
    PublicChatResponse,
    PublicClone,
    PublicCloneCard,
    PublicCloneList,
    PublicMessage,
    PublicSource,
)
from app.services import captcha, monitoring, platform_service, public_session_service
from app.services.errors import ForbiddenError, NotFoundError
from app.services.rate_limit import RateLimitedError, check_public_rate
from app.voice.routing import effective_voice
from app.voice.speech_to_text import TranscribedSpeech, transcribe_audio
from app.voice.text_to_speech import generate_speech

logger = logging.getLogger(__name__)

NOT_FOUND = "AI Clone not found"
CHAT_OFF = "Public chat is turned off for this AI Clone."
VOICE_OFF = "Voice isn't available for visitors of this AI Clone."
AVATAR_OFF = "Avatar videos aren't available for visitors of this AI Clone."
LIMIT_REACHED = "This conversation has reached its message limit. Start a new conversation."
PLATFORM_CHAT_OFF = "Public chat is temporarily turned off."
DISCOVERY_OFF = "Public discovery is currently turned off."
# Common prompt-injection phrasings, recorded as SUSPICIOUS_REQUEST (the message
# itself is never stored in the event; the public prompt already resists them).
_SUSPICIOUS = re.compile(
    r"ignore (all |any )?(the )?(previous|prior|above) (instructions|rules)|system prompt|"
    r"developer (mode|message)|reveal (your|the) (prompt|instructions)|jailbreak|"
    r"api[ _-]?key|private (documents?|memories)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Visitor:
    """Who is asking, for rate limits only (never stored)."""

    address: str


# --- Lookup and profile -------------------------------------------------------------


def get_public_clone(db: Session, slug: str) -> CloneProfile:
    clone = db.scalar(select(CloneProfile).where(CloneProfile.slug == slug.lower()))
    if clone is None or clone.visibility not in ("public", "unlisted") or clone.status != "active":
        raise NotFoundError(NOT_FOUND)
    if not clone.owner.is_active:  # an administrator disabled the owner's account
        raise NotFoundError(NOT_FOUND)
    return clone


def voice_available(clone: CloneProfile) -> bool:
    return clone.public_voice_enabled and clone.voice_enabled and clone.voice_consent_given


def realtime_voice_available(clone: CloneProfile) -> bool:
    """Phase 17: visitors may start a live voice conversation (feature on, provider set up,
    owner switch on with public chat and public voice)."""
    from app.realtime_voice import permissions
    from app.realtime_voice.exceptions import RealtimeVoiceError

    try:
        permissions.active_provider()
    except RealtimeVoiceError:
        return False
    return voice_available(clone) and permissions.clone_problem(clone) is None and permissions.public_allowed(clone)


def avatar_settings_allow(clone: CloneProfile) -> bool:
    """The switches and consents for public avatars (the photo itself is checked separately)."""
    return bool(
        get_settings().avatar_feature_enabled
        and clone.public_avatar_enabled
        and clone.avatar_enabled
        and clone.avatar_consent_given
        and clone.voice_enabled
        and clone.voice_consent_given
    )


def avatar_available(db: Session, clone: CloneProfile) -> bool:
    if not avatar_settings_allow(clone):
        return False
    avatar = avatar_service.active_avatar(db, clone)
    return avatar is not None and avatar.status == "ready"


def avatar_image_url(db: Session, clone: CloneProfile) -> str | None:
    """The clone's picture for visitors: its avatar only when the owner made avatars public."""
    if avatar_available(db, clone):
        return f"/api/public/clones/{clone.slug}/avatar-image"
    return clone.avatar_url


def profile(db: Session, clone: CloneProfile) -> PublicClone:
    chat_on = clone.public_chat_enabled and platform_service.current(db).public_chat_enabled
    return PublicClone(
        id=clone.id,
        name=clone.name,
        slug=clone.slug,
        tagline=clone.tagline,
        bio=clone.bio,
        profession=clone.profession,
        skills=list(clone.skills or []),
        preferred_language=clone.preferred_language,
        avatar_url=avatar_image_url(db, clone),
        visibility=clone.visibility,  # type: ignore[arg-type]
        public_chat_enabled=chat_on,
        voice_enabled=chat_on and voice_available(clone),
        avatar_enabled=chat_on and avatar_available(db, clone),
        realtime_voice_available=chat_on and realtime_voice_available(clone),
    )


def avatar_image_file(db: Session, clone: CloneProfile):
    if not avatar_available(db, clone):
        raise NotFoundError("No public avatar")
    return avatar_service.image_path(avatar_service.active_avatar(db, clone))


# --- Discovery ----------------------------------------------------------------------


def discover(
    db: Session,
    *,
    page: int,
    limit: int,
    search: str | None = None,
    profession: str | None = None,
    skill: str | None = None,
    language: str | None = None,
) -> PublicCloneList:
    """Public clones with public chat on. Searches the public profile only, never knowledge.
    An administrator can turn discovery off; direct links keep working."""
    if not platform_service.current(db).public_clone_discovery_enabled:
        raise ForbiddenError(DISCOVERY_OFF)
    query = (
        select(CloneProfile)
        .join(User, User.id == CloneProfile.owner_id)
        .where(
            CloneProfile.visibility == "public",
            CloneProfile.status == "active",
            CloneProfile.public_chat_enabled.is_(True),
            User.is_active.is_(True),
        )
    )

    def like(text: str) -> str:
        escaped = text.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return f"%{escaped}%"

    skills_text = func.lower(cast(CloneProfile.skills, String))
    if search and search.strip():
        pattern = like(search)
        query = query.where(
            or_(
                func.lower(CloneProfile.name).like(pattern, escape="\\"),
                func.lower(func.coalesce(CloneProfile.tagline, "")).like(pattern, escape="\\"),
                func.lower(func.coalesce(CloneProfile.profession, "")).like(pattern, escape="\\"),
                skills_text.like(pattern, escape="\\"),
            )
        )
    if profession and profession.strip():
        query = query.where(func.lower(func.coalesce(CloneProfile.profession, "")).like(like(profession), escape="\\"))
    if skill and skill.strip():
        query = query.where(skills_text.like(like(skill), escape="\\"))
    if language and language.strip():
        query = query.where(func.lower(func.coalesce(CloneProfile.preferred_language, "")) == language.strip().lower())

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(CloneProfile.name, CloneProfile.id).offset((page - 1) * limit).limit(limit))
    items = [
        PublicCloneCard(
            name=c.name,
            slug=c.slug,
            tagline=c.tagline,
            profession=c.profession,
            skills=list(c.skills or [])[:8],
            preferred_language=c.preferred_language,
            avatar_url=avatar_image_url(db, c),
        )
        for c in rows
    ]
    return PublicCloneList(items=items, page=page, limit=limit, total=total)


# --- Sessions -----------------------------------------------------------------------


def _require_chat(clone: CloneProfile) -> None:
    # The platform switch is read on every public request (maintenance check), so the
    # cached value is current.
    if not platform_service.cached().public_chat_enabled:
        raise ForbiddenError(PLATFORM_CHAT_OFF)
    if not clone.public_chat_enabled:
        raise ForbiddenError(CHAT_OFF)


def session_for(db: Session, clone: CloneProfile, token: str | None) -> PublicChatSession:
    _require_chat(clone)
    return public_session_service.require(db, clone, token)


def _session_for_chat(
    db: Session, clone: CloneProfile, visitor: Visitor, token: str | None, captcha_token: str | None
) -> tuple[PublicChatSession, str]:
    if token:
        session = public_session_service.find(db, clone, token)
        if session is not None:
            return session, token
        raise NotFoundError(public_session_service.EXPIRED)
    check_public_rate("session", visitor.address)
    captcha.verify(captcha_token, visitor.address)
    return public_session_service.create(db, clone)


# --- Chat ---------------------------------------------------------------------------


async def chat(
    db: Session, clone: CloneProfile, visitor: Visitor, request: PublicChatRequest, header_token: str | None
) -> PublicChatResponse:
    _require_chat(clone)
    token = request.session_id or header_token
    check_public_rate("chat", visitor.address)
    if _SUSPICIOUS.search(request.message):
        monitoring.security(
            "SUSPICIOUS_REQUEST", "medium", details={"clone_id": str(clone.id), "kind": "prompt_injection", "ip": visitor.address}
        )
    session, token = await run_in_threadpool(_session_for_chat, db, clone, visitor, token, request.captcha_token)
    if public_session_service.messages_left(session) <= 0:
        raise RateLimitedError(LIMIT_REACHED)

    settings = get_settings()
    question = await run_in_threadpool(
        public_session_service.add_message, db, session, "user", request.message, request.input_mode
    )
    history = await run_in_threadpool(
        public_session_service.recent_history, db, session, settings.max_conversation_messages, exclude=question.id
    )
    context = await run_in_threadpool(public_rag_pipeline.retrieve_public_context, db, clone, request.message)
    reply = await public_rag_pipeline.generate_public_response(clone, request.message, context, history)
    if not reply.text.strip():
        raise LLMError("The model returned an empty answer")
    answer = await run_in_threadpool(public_session_service.add_message, db, session, "assistant", reply.text)
    titles = list(dict.fromkeys(hit.title for hit in context.hits))  # public documents only
    logger.info("Public chat for clone %s answered in %d ms", clone.id, reply.latency_ms)
    monitoring.usage("PUBLIC_CHAT_MESSAGE", provider=reply.provider, clone_id=clone.id, duration_ms=reply.latency_ms)
    return PublicChatResponse(
        session_id=token,
        expires_at=public_session_service.aware(session.expires_at),
        message=PublicMessage.model_validate(answer),
        sources=[PublicSource(title=title) for title in titles],
        messages_left=public_session_service.messages_left(session),
    )


# --- Voice --------------------------------------------------------------------------


def _require_voice(clone: CloneProfile) -> None:
    _require_chat(clone)
    if not voice_available(clone):
        raise ForbiddenError(VOICE_OFF)


async def transcribe(
    clone: CloneProfile, visitor: Visitor, data: bytes, filename: str | None, content_type: str | None
) -> TranscribedSpeech:
    _require_voice(clone)
    check_public_rate("voice", visitor.address)
    hint = clone.preferred_language or clone.voice_language
    return await transcribe_audio(data, filename, content_type, language_hint=hint, clone_id=clone.id)


def audio_url(slug: str, audio_id: str) -> str:
    return f"/api/public/clones/{slug}/audio/{audio_id}"


async def speak(db: Session, clone: CloneProfile, visitor: Visitor, token: str | None, message_id: uuid.UUID) -> str:
    """Speech for one of the clone's answers in this visitor's session."""
    from app.services.voice_service import speech_language

    _require_voice(clone)
    session = await run_in_threadpool(public_session_service.require, db, clone, token)
    message = await run_in_threadpool(public_session_service.get_message, db, session, message_id)
    if message.role != "assistant":
        raise NotFoundError("Message not found")
    check_public_rate("voice", visitor.address)
    # Stored under the session id: only this visitor's session can fetch it.
    speech = await generate_speech(
        message.content,
        effective_voice(clone),
        speech_language(clone, message.content),
        user_id=session.id,
        cache_key=f"public:{message.id}",
        clone_id=clone.id,
    )
    return audio_url(clone.slug, speech.audio_id)


def audio_file(db: Session, clone: CloneProfile, token: str | None, audio_id: str):
    from app.voice.storage import get_voice_store

    session = session_for(db, clone, token)
    path = get_voice_store().find(session.id, audio_id)
    if path is None:
        raise NotFoundError("Audio not found or expired")
    return path


# --- Avatar videos ------------------------------------------------------------------


def create_video(
    db: Session, clone: CloneProfile, visitor: Visitor, token: str | None, message_id: uuid.UUID
) -> AvatarVideoJob:
    session = session_for(db, clone, token)
    if not avatar_available(db, clone):
        raise ForbiddenError(AVATAR_OFF)
    message = public_session_service.get_message(db, session, message_id)
    if message.role != "assistant":
        raise NotFoundError("Message not found")
    provider = avatar_factory.get_lipsync_provider()  # 503 if videos are off on the server
    check_public_rate("avatar", visitor.address)
    avatar = avatar_service.active_avatar(db, clone)
    job = AvatarVideoJob(
        clone_id=clone.id,
        owner_id=clone.owner_id,
        public_session_id=session.id,
        public_message_id=message.id,
        avatar_id=avatar.id,
        text=message.content,
        provider=provider.name,
        status="queued",
        progress=0,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    jobs.submit(job.id)
    return job


def get_job(db: Session, clone: CloneProfile, token: str | None, job_id: uuid.UUID) -> AvatarVideoJob:
    session = session_for(db, clone, token)
    job = db.get(AvatarVideoJob, job_id)
    if job is None or job.clone_id != clone.id or job.public_session_id != session.id:
        raise NotFoundError("Video job not found")
    return job


def video_url(clone: CloneProfile, job: AvatarVideoJob) -> str:
    return f"/api/public/clones/{clone.slug}/avatar/jobs/{job.id}/video"
