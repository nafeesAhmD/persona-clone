"""Developer platform (Phase 14): API keys, webhook endpoints and webhook deliveries.

Secrets are never stored in plain text:
- API keys: only a keyed hash (HMAC-SHA256 with a server pepper) and a short display
  prefix. The full key is shown once, at creation or rotation.
- Webhook secrets: only a random salt and a hash. The signing secret is re-derived on
  the server from the salt and a server key (app/developer/secrets.py), so a database
  leak alone reveals no secret. It is shown once, at creation or rotation.
An API key or webhook belongs to a user (personal) or to an organization, never both.
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

_JSON = JSON().with_variant(JSONB(), "postgresql")
_ONE_OWNER = "(user_id IS NULL) <> (organization_id IS NULL)"


class ApiKey(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "api_keys"
    __table_args__ = (
        CheckConstraint(_ONE_OWNER, name="ck_api_keys_one_owner"),
        Index("ix_api_keys_user_id", "user_id"),
        Index("ix_api_keys_organization_id", "organization_id"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    # Who created it (kept for audit; an organization key stays the organization's).
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(100))
    # e.g. "ahc_live_Ab3dE6gH" - enough to recognise a key, useless to use it.
    key_prefix: Mapped[str] = mapped_column(String(24))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list[str]] = mapped_column(_JSON, default=list)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WebhookEndpoint(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "webhook_endpoints"
    __table_args__ = (
        CheckConstraint(_ONE_OWNER, name="ck_webhook_endpoints_one_owner"),
        Index("ix_webhook_endpoints_user_id", "user_id"),
        Index("ix_webhook_endpoints_organization_id", "organization_id"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    url: Mapped[str] = mapped_column(String(2000))
    secret_salt: Mapped[str] = mapped_column(String(64))
    secret_hash: Mapped[str] = mapped_column(String(64))
    events: Mapped[list[str]] = mapped_column(_JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    last_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class WebhookDelivery(UUIDPrimaryKeyMixin, Base):
    """One event sent (or to be sent) to one endpoint. Retried with exponential backoff."""

    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'delivering', 'delivered', 'failed')", name="ck_webhook_deliveries_status"),
        Index("ix_webhook_deliveries_webhook_created", "webhook_id", "created_at"),
        Index("ix_webhook_deliveries_due", "status", "next_retry_at"),
        Index("ix_webhook_deliveries_event_id", "event_id"),
    )

    webhook_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("webhook_endpoints.id", ondelete="CASCADE"))
    # The same event id is sent on every retry, so consumers can drop duplicates.
    event_id: Mapped[str] = mapped_column(String(40))
    event_type: Mapped[str] = mapped_column(String(40))
    # The event envelope {id, type, timestamp, data}; data never holds secrets.
    payload: Mapped[dict] = mapped_column(_JSON, default=dict)
    status: Mapped[str] = mapped_column(String(12), default="pending", server_default="pending")
    response_status: Mapped[int | None] = mapped_column(Integer)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(String(300))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
