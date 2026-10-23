"""Administration and monitoring records.

These are operational logs, deliberately without foreign keys on user/clone ids:
they must never block deleting a user or clone, and they never hold content
(no passwords, tokens, keys, prompts, documents or messages). Old rows are
removed by the hourly cleanup after their *_RETENTION_DAYS.
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, false, func, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

_JSON = JSON().with_variant(JSONB(), "postgresql")


class AdminAuditLog(UUIDPrimaryKeyMixin, Base):
    """Every security-sensitive admin action: who did what to which target."""

    __tablename__ = "admin_audit_logs"
    __table_args__ = (Index("ix_admin_audit_logs_target", "target_type", "target_id"),)

    admin_user_id: Mapped[uuid.UUID] = mapped_column(index=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    target_type: Mapped[str] = mapped_column(String(30))
    target_id: Mapped[str | None] = mapped_column(String(64))
    # Safe context only, e.g. {"before": "active", "after": "disabled"}.
    details: Mapped[dict] = mapped_column("metadata", _JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class SecurityEvent(UUIDPrimaryKeyMixin, Base):
    """Logins, denied access, invalid tokens, rate limits, suspicious requests."""

    __tablename__ = "security_events"

    event_type: Mapped[str] = mapped_column(String(40), index=True)
    severity: Mapped[str] = mapped_column(String(10), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    # Operational data, visible to admins only and deleted after SECURITY_LOG_RETENTION_DAYS.
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    details: Mapped[dict] = mapped_column("metadata", _JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class UsageEvent(UUIDPrimaryKeyMixin, Base):
    """One AI/media operation, for monitoring and cost estimates (counts and sizes only)."""

    __tablename__ = "usage_events"

    user_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    clone_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    provider: Mapped[str | None] = mapped_column(String(40), index=True)
    # Units depend on the event: estimated tokens (LLM), characters (TTS), seconds (STT, video).
    input_units: Mapped[float | None] = mapped_column(Float)
    output_units: Mapped[float | None] = mapped_column(Float)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    # Developer API calls (Phase 14): which key and organization, which endpoint
    # (ids masked) and the HTTP status. Never the key itself or request bodies.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    endpoint: Mapped[str | None] = mapped_column(String(200))
    status_code: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class ErrorEvent(UUIDPrimaryKeyMixin, Base):
    """A server-side or provider error, with safe diagnostics (no request bodies or secrets)."""

    __tablename__ = "error_events"

    error_type: Mapped[str] = mapped_column(String(80))
    category: Mapped[str] = mapped_column(String(30), index=True)
    method: Mapped[str | None] = mapped_column(String(10))
    endpoint: Mapped[str | None] = mapped_column(String(300))
    status_code: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column()
    clone_id: Mapped[uuid.UUID | None] = mapped_column()
    request_id: Mapped[str | None] = mapped_column(String(40), index=True)
    # The safe, user-facing message and where it happened (module:line), never values.
    message: Mapped[str | None] = mapped_column(String(300))
    location: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class PlatformSettings(TimestampMixin, Base):
    """Platform-wide switches, a single row (id = 1). Secrets never live here."""

    __tablename__ = "platform_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    maintenance_mode: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    public_registration_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    public_clone_discovery_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    public_chat_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # Optional overrides of the per-minute rate limits, e.g. {"public_chat": 5, "login": 3}.
    rate_limits: Mapped[dict] = mapped_column(_JSON, default=dict)
    updated_by: Mapped[uuid.UUID | None] = mapped_column()
