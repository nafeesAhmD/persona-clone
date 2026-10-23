"""Real-time voice: settings, session lifecycle, limits, usage and analytics.

Authorization always comes from the server: the logged-in user (cookie) and the
clone's own rules, or a visitor's public chat token. Nothing the browser says about
users, owners or permissions is trusted.
"""

import logging
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.events import record_event
from app.billing import service as billing_service
from app.billing.exceptions import UsageLimitError
from app.core.config import get_settings
from app.models import CloneProfile, RealtimeVoiceSession, User
from app.models.realtime_voice import LIVE_STATUSES
from app.realtime_voice import permissions
from app.realtime_voice.db import open_db
from app.realtime_voice.exceptions import RealtimeVoiceError
from app.realtime_voice.provider_base import TurnContext
from app.realtime_voice.providers import get_provider
from app.realtime_voice.safety import hash_ticket, new_ticket
from app.realtime_voice.schemas import (
    RealtimeCapabilities,
    RealtimeLimits,
    RealtimeSettings,
    RealtimeSettingsUpdate,
    SessionCreate,
    SessionCreated,
    SessionStatus,
)
from app.realtime_voice.session_manager import LiveSession, manager
from app.services import conversation_service, monitoring, public_service
from app.services.errors import NotFoundError
from app.services.rate_limit import RateLimitedError, SlidingWindowLimiter

logger = logging.getLogger(__name__)

WS_PATH = "/api/realtime/sessions/{session_id}/ws"
FINAL_STATUSES = ("ended", "failed", "expired")
QUOTA_KEY = "realtime_voice_sessions"
session_limiter = SlidingWindowLimiter()


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    """SQLite gives naive datetimes back; they are UTC."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _event(event_type: str, row: RealtimeVoiceSession, *, metadata: dict, duration_ms=None, success=True) -> None:
    """Analytics record (safe values only). Never breaks the session."""
    try:
        with open_db() as db:
            record_event(
                db,
                event_type,
                clone_id=row.clone_id,
                user_id=row.owner_id,
                session_id=str(row.id),
                source="public" if row.is_public else "app",
                metadata={"provider": row.provider, **metadata},
                duration_ms=duration_ms,
                success=success,
            )
    except Exception as exc:  # noqa: BLE001 - analytics must never break a call
        logger.warning("Could not record %s: %s", event_type, type(exc).__name__)


# --- Settings -------------------------------------------------------------------------


def limits() -> RealtimeLimits:
    settings = get_settings()
    return RealtimeLimits(
        max_duration_seconds=settings.realtime_voice_max_duration_seconds,
        session_ttl_seconds=settings.realtime_voice_session_ttl_seconds,
        max_utterance_seconds=settings.realtime_voice_max_utterance_seconds,
        max_utterance_bytes=settings.realtime_voice_max_utterance_bytes,
    )


def _capabilities(clone: CloneProfile) -> RealtimeCapabilities:
    provider = get_provider(get_settings().realtime_voice_provider)
    if provider is None:
        return RealtimeCapabilities(
            interruption=False, streaming_text=False, server_speech=False, cloned_voice=False, languages=[]
        )
    return RealtimeCapabilities(**provider.capabilities(clone))


def settings_of(clone: CloneProfile) -> RealtimeSettings:
    reason = None
    try:
        permissions.active_provider()
    except RealtimeVoiceError as exc:
        reason = exc.code
    reason = reason or permissions.clone_problem(clone)
    return RealtimeSettings(
        available=reason is None,
        reason=reason,
        provider=get_settings().realtime_voice_provider,
        enabled=clone.realtime_voice_enabled,
        public_enabled=clone.public_realtime_voice_enabled,
        speech_mode=clone.realtime_speech_mode if clone.realtime_speech_mode in ("voice", "browser") else "voice",
        capabilities=_capabilities(clone),
        limits=limits(),
    )


def update_settings(db: Session, clone: CloneProfile, data: RealtimeSettingsUpdate) -> RealtimeSettings:
    changes = data.model_dump(exclude_unset=True, exclude_none=True)
    if changes.get("public_enabled"):
        if not (clone.public_chat_enabled and clone.public_voice_enabled and clone.visibility != "private"):
            raise RealtimeVoiceError("invalid_settings")
    if "enabled" in changes:
        clone.realtime_voice_enabled = changes["enabled"]
    if "public_enabled" in changes:
        clone.public_realtime_voice_enabled = changes["public_enabled"]
    if "speech_mode" in changes:
        clone.realtime_speech_mode = changes["speech_mode"]
    db.commit()
    db.refresh(clone)
    return settings_of(clone)


# --- Limits ---------------------------------------------------------------------------


def _rate(key: str) -> None:
    try:
        session_limiter.check(key, get_settings().realtime_voice_rate_limit_per_minute)
    except RateLimitedError as exc:
        raise RealtimeVoiceError("rate_limited") from exc


def _live_rows(db: Session, *, owner_id=None, visitor_key=None) -> list[RealtimeVoiceSession]:
    who = RealtimeVoiceSession.owner_id == owner_id if owner_id else RealtimeVoiceSession.visitor_key == visitor_key
    rows = db.scalars(select(RealtimeVoiceSession).where(who, RealtimeVoiceSession.status.in_(LIVE_STATUSES))).all()
    now = _now()
    return [row for row in rows if _aware(row.expires_at) > now]


def _check_concurrency(db: Session, *, owner_id=None, visitor_key=None) -> None:
    if len(_live_rows(db, owner_id=owner_id, visitor_key=visitor_key)) >= get_settings().realtime_voice_max_concurrent_sessions:
        raise RealtimeVoiceError("too_many_sessions")


def _check_quota(db: Session, user: User) -> None:
    try:
        billing_service.check_limit(db, user.id, QUOTA_KEY)
    except UsageLimitError as exc:
        raise RealtimeVoiceError("quota_exceeded") from exc


# --- Sessions -------------------------------------------------------------------------


def _open(
    db: Session,
    provider_name: str,
    clone: CloneProfile,
    *,
    owner_id: uuid.UUID | None,
    visitor_key: str | None,
    conversation_id: uuid.UUID | None,
    public_token: str | None = None,
    visitor_address: str = "unknown",
) -> SessionCreated:
    settings = get_settings()
    if settings.realtime_voice_audio_retention_enabled:
        logger.warning("REALTIME_VOICE_AUDIO_RETENTION_ENABLED is set, but audio retention isn't implemented: no audio is stored")
    now = _now()
    ticket = new_ticket()
    speech_mode = clone.realtime_speech_mode if clone.realtime_speech_mode in ("voice", "browser") else "voice"
    row = RealtimeVoiceSession(
        clone_id=clone.id,
        owner_id=owner_id,
        visitor_key=visitor_key,
        conversation_id=conversation_id,
        provider=provider_name,
        status="created",
        is_public=visitor_key is not None,
        expires_at=now + timedelta(seconds=settings.realtime_voice_session_ttl_seconds),
        session_metadata={"speech_mode": speech_mode},
        ticket_hash=hash_ticket(ticket),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    ticket_ttl = min(settings.realtime_voice_ticket_ttl_seconds, settings.realtime_voice_session_ttl_seconds)
    manager.add(
        LiveSession(
            ctx=TurnContext(
                session_id=row.id,
                clone_id=clone.id,
                user_id=owner_id,
                is_public=row.is_public,
                speech_mode=speech_mode,
                conversation_id=conversation_id,
                public_token=public_token,
                visitor_address=visitor_address,
            ),
            ticket_hash=row.ticket_hash,
            ticket_expires=time.monotonic() + ticket_ttl,
            max_duration_seconds=settings.realtime_voice_max_duration_seconds,
        )
    )
    return SessionCreated(
        session_id=row.id,
        status=row.status,
        provider=row.provider,
        conversation_id=conversation_id,
        ws_path=WS_PATH.format(session_id=row.id),
        ticket=ticket,
        ticket_expires_at=now + timedelta(seconds=ticket_ttl),
        expires_at=_aware(row.expires_at),
        max_duration_seconds=settings.realtime_voice_max_duration_seconds,
        speech_mode=speech_mode,
        capabilities=_capabilities(clone),
    )


def create_session(db: Session, clone: CloneProfile, user: User, data: SessionCreate) -> SessionCreated:
    provider = permissions.active_provider()
    permissions.require_clone(clone)
    _rate(f"user:{user.id}")
    conversation_id = None
    if data.conversation_id is not None:
        conversation = conversation_service.get_owned(db, data.conversation_id, user)
        if conversation.clone_id != clone.id:
            raise NotFoundError(conversation_service.NOT_FOUND)
        conversation_id = conversation.id
    _check_concurrency(db, owner_id=user.id)
    _check_quota(db, user)
    return _open(db, provider.name, clone, owner_id=user.id, visitor_key=None, conversation_id=conversation_id)


def create_public_session(db: Session, clone: CloneProfile, token: str | None, visitor_address: str) -> SessionCreated:
    provider = permissions.active_provider()
    permissions.require_public(clone)
    public_session = public_service.session_for(db, clone, token)  # a valid public chat token
    _rate(f"public:{visitor_address}")
    visitor_key = str(public_session.id)
    _check_concurrency(db, visitor_key=visitor_key)
    return _open(
        db,
        provider.name,
        clone,
        owner_id=None,
        visitor_key=visitor_key,
        conversation_id=None,
        public_token=token,
        visitor_address=visitor_address,
    )


def _status(row: RealtimeVoiceSession) -> SessionStatus:
    return SessionStatus(
        session_id=row.id,
        status=row.status,
        provider=row.provider,
        conversation_id=row.conversation_id,
        started_at=_aware(row.started_at),
        ended_at=_aware(row.ended_at),
        duration_seconds=row.duration_seconds,
        error_code=row.error_code,
        expires_at=_aware(row.expires_at),
    )


def _expire_if_due(db: Session, row: RealtimeVoiceSession) -> None:
    if row.status in ("created", "connecting") and _aware(row.expires_at) <= _now():
        finalize(db, row, "expired")


def _own_row(db: Session, clone_id: uuid.UUID, session_id: uuid.UUID, user: User) -> RealtimeVoiceSession:
    row = db.get(RealtimeVoiceSession, session_id)
    if row is None or row.owner_id != user.id or row.clone_id != clone_id:
        raise RealtimeVoiceError("session_not_found")
    return row


def get_session(db: Session, clone_id: uuid.UUID, session_id: uuid.UUID, user: User) -> SessionStatus:
    row = _own_row(db, clone_id, session_id, user)
    _expire_if_due(db, row)
    return _status(row)


def end_session(db: Session, clone_id: uuid.UUID, session_id: uuid.UUID, user: User) -> SessionStatus:
    row = _own_row(db, clone_id, session_id, user)
    _end(db, row)
    return _status(row)


def end_public_session(db: Session, clone: CloneProfile, session_id: uuid.UUID, token: str | None) -> SessionStatus:
    public_session = public_service.session_for(db, clone, token)
    row = db.get(RealtimeVoiceSession, session_id)
    if row is None or row.clone_id != clone.id or row.visitor_key != str(public_session.id):
        raise RealtimeVoiceError("session_not_found")
    _end(db, row)
    return _status(row)


def _end(db: Session, row: RealtimeVoiceSession) -> None:
    """Idempotent. A connected WebSocket is told to close (it runs on its own loop)."""
    live = manager.get(row.id)
    turns = live.extra.get("turns") if live else None
    if live is not None:
        live.request_end("client")
    finalize(db, row, "client", turns=turns)


def finalize(
    db: Session, row: RealtimeVoiceSession, reason: str, *, error_code: str | None = None, turns: int | None = None
) -> None:
    """End a session once: status, duration, usage record and analytics event."""
    if row.status in FINAL_STATUSES:
        return
    now = _now()
    row.status = "expired" if reason == "expired" else ("failed" if error_code else "ended")
    row.ended_at = now
    row.error_code = error_code or ("session_expired" if reason == "expired" else None)
    if turns is not None:
        row.turns = turns
    started = _aware(row.started_at)
    row.duration_seconds = round((now - started).total_seconds(), 2) if started else 0.0
    row.session_metadata = {**(row.session_metadata or {}), "end_reason": reason}
    db.commit()
    live = manager.get(row.id)
    if live is not None and not live.connected:
        manager.remove(row.id)  # a ticket that was never used dies with its session
    duration_ms = int((row.duration_seconds or 0) * 1000)
    monitoring.usage(
        "REALTIME_VOICE_SESSION",
        provider=row.provider,
        status="failed" if error_code else "success",
        user_id=row.owner_id,
        clone_id=row.clone_id,
        input_units=row.turns,
        duration_ms=duration_ms,
    )
    _event(
        "realtime_voice_session_ended",
        row,
        metadata={"reason": reason, "turns": row.turns, "error": error_code},
        duration_ms=duration_ms,
        success=error_code is None,
    )
    logger.info("Real-time voice session %s %s after %.1fs (%d turns)", row.id, row.status, row.duration_seconds, row.turns)


def mark_connected(session_id: uuid.UUID, max_duration_seconds: int) -> None:
    with open_db() as db:
        row = db.get(RealtimeVoiceSession, session_id)
        if row is None:
            return
        now = _now()
        row.status = "connected"
        row.started_at = now
        row.expires_at = now + timedelta(seconds=max_duration_seconds)
        db.commit()
        _event("realtime_voice_session_started", row, metadata={"speech_mode": (row.session_metadata or {}).get("speech_mode")})


def mark_finished(
    session_id: uuid.UUID,
    reason: str,
    turns: int,
    error_code: str | None = None,
    conversation_id: uuid.UUID | None = None,
) -> None:
    """The WebSocket has finished (any reason): record it and drop the live entry."""
    with open_db() as db:
        row = db.get(RealtimeVoiceSession, session_id)
        if row is not None:
            if conversation_id is not None and row.conversation_id is None:
                row.conversation_id = conversation_id
                db.commit()
            finalize(db, row, reason, error_code=error_code, turns=turns)
    manager.remove(session_id)


def connection_failed(session_id: uuid.UUID, code: str) -> None:
    """A WebSocket that couldn't be set up (bad ticket, origin, expiry). Safe codes only."""
    with open_db() as db:
        row = db.get(RealtimeVoiceSession, session_id)
        if row is not None:
            _event("realtime_voice_connection_failed", row, metadata={"code": code}, success=False)


def provider_error(session_id: uuid.UUID, category: str) -> None:
    with open_db() as db:
        row = db.get(RealtimeVoiceSession, session_id)
        if row is not None:
            _event("realtime_voice_provider_error", row, metadata={"category": category}, success=False)

