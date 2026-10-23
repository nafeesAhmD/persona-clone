"""Anonymous visitor sessions of public clones.

A session is identified by a random token (secrets.token_urlsafe(32)) that only
the visitor's browser holds; the database stores its SHA-256 hash. Sessions
belong to one clone, expire after PUBLIC_SESSION_TTL_HOURS and allow at most
MAX_PUBLIC_MESSAGES_PER_SESSION visitor messages. No visitor identity is kept.
"""

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai.base import ChatTurn
from app.core.config import get_settings
from app.models import CloneProfile, PublicChatMessage, PublicChatSession
from app.services.errors import NotFoundError

logger = logging.getLogger(__name__)

EXPIRED = "This conversation has ended. Start a new conversation."


def _now() -> datetime:
    return datetime.now(UTC)


def aware(value: datetime) -> datetime:
    # SQLite (tests) returns naive datetimes; PostgreSQL returns aware ones.
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create(db: Session, clone: CloneProfile) -> tuple[PublicChatSession, str]:
    token = secrets.token_urlsafe(32)
    now = _now()
    session = PublicChatSession(
        clone_id=clone.id,
        session_token_hash=hash_token(token),
        expires_at=now + timedelta(hours=get_settings().public_session_ttl_hours),
        message_count=0,
        created_at=now,
        updated_at=now,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session, token


def find(db: Session, clone: CloneProfile, token: str | None) -> PublicChatSession | None:
    """The clone's unexpired session for this token, or None."""
    if not token or len(token) > 200:
        return None
    session = db.scalar(select(PublicChatSession).where(PublicChatSession.session_token_hash == hash_token(token)))
    if session is None or session.clone_id != clone.id or aware(session.expires_at) <= _now():
        return None
    return session


def require(db: Session, clone: CloneProfile, token: str | None) -> PublicChatSession:
    session = find(db, clone, token)
    if session is None:
        raise NotFoundError(EXPIRED)
    return session


def messages_left(session: PublicChatSession) -> int:
    return max(0, get_settings().max_public_messages_per_session - session.message_count)


def add_message(
    db: Session, session: PublicChatSession, role: str, content: str, input_mode: str = "text"
) -> PublicChatMessage:
    now = _now()
    message = PublicChatMessage(
        session_id=session.id, role=role, content=content, input_mode=input_mode, created_at=now, updated_at=now
    )
    db.add(message)
    if role == "user":
        session.message_count += 1
    session.updated_at = now
    db.commit()
    db.refresh(message)
    return message


def messages_of(db: Session, session: PublicChatSession) -> list[PublicChatMessage]:
    return list(
        db.scalars(
            select(PublicChatMessage)
            .where(PublicChatMessage.session_id == session.id)
            .order_by(PublicChatMessage.created_at, PublicChatMessage.id)
        )
    )


def get_message(db: Session, session: PublicChatSession, message_id) -> PublicChatMessage:
    message = db.get(PublicChatMessage, message_id)
    if message is None or message.session_id != session.id:
        raise NotFoundError("Message not found")
    return message


def recent_history(db: Session, session: PublicChatSession, limit: int, *, exclude=None) -> list[ChatTurn]:
    """The last `limit` messages as alternating user/assistant turns, oldest first."""
    query = select(PublicChatMessage).where(PublicChatMessage.session_id == session.id)
    if exclude is not None:
        query = query.where(PublicChatMessage.id != exclude)
    rows = list(db.scalars(query.order_by(PublicChatMessage.created_at.desc()).limit(limit)))
    turns: list[ChatTurn] = []
    for message in reversed(rows):
        if turns and turns[-1]["role"] == message.role:
            turns[-1] = {"role": message.role, "content": f"{turns[-1]['content']}\n\n{message.content}"}
        else:
            turns.append({"role": message.role, "content": message.content})  # type: ignore[typeddict-item]
    while turns and turns[0]["role"] != "user":
        turns.pop(0)
    if turns and turns[-1]["role"] == "user":
        turns.pop()
    return turns


def end(db: Session, session: PublicChatSession) -> None:
    db.delete(session)
    db.commit()


def cleanup_expired(db: Session) -> int:
    """Delete expired sessions and their messages."""
    result = db.execute(delete(PublicChatSession).where(PublicChatSession.expires_at <= _now()))
    db.commit()
    if result.rowcount:
        logger.info("Removed %d expired public chat sessions", result.rowcount)
    return result.rowcount
