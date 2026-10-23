"""Real-time voice sessions (Phase 17). See app/realtime_voice.

One row per live conversation: who, which clone, status and timings. Never audio,
transcripts or the connection ticket (only its SHA-256). The spoken turns are saved
as ordinary conversation messages, exactly like chat.
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, false
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

_JSON = JSON().with_variant(JSONB(), "postgresql")

SESSION_STATUSES = ("created", "connecting", "connected", "ended", "failed", "expired")
LIVE_STATUSES = ("created", "connecting", "connected")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class RealtimeVoiceSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "realtime_voice_sessions"
    __table_args__ = (
        CheckConstraint(_in("status", SESSION_STATUSES), name="ck_realtime_voice_sessions_status"),
        Index("ix_realtime_voice_sessions_owner_created", "owner_id", "created_at"),
        Index("ix_realtime_voice_sessions_status", "status"),
    )

    clone_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clone_profiles.id", ondelete="CASCADE"), index=True)
    # The logged-in user (None for a public visitor).
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # Public visitors: the public chat session's id (its token is never stored here).
    visitor_key: Mapped[str | None] = mapped_column(String(64))
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"))
    provider: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(12), default="created", server_default="created")
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    turns: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(40))
    # Safe values only (speech mode, end reason, interrupt count...): no text, no secrets.
    session_metadata: Mapped[dict] = mapped_column("metadata", _JSON, default=dict)
    ticket_hash: Mapped[str | None] = mapped_column(String(64))
