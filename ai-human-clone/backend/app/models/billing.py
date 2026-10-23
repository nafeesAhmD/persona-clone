"""Billing models for Phase 12."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

_JSON = JSON().with_variant(JSONB(), "postgresql")

SUBSCRIPTION_STATUSES = (
    "trialing",
    "active",
    "past_due",
    "cancelled",
    "expired",
    "incomplete",
)
BILLING_INTERVALS = ("month", "year")


class Plan(TimestampMixin, Base):
    __tablename__ = "plans"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_plans_slug"),
        Index("ix_plans_is_active", "is_active"),
        Index("ix_plans_is_public", "is_public"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(80))  # unique via uq_plans_slug
    description: Mapped[str | None] = mapped_column(String(500))
    price: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    billing_interval: Mapped[str] = mapped_column(String(10), default="month")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    limits: Mapped[dict] = mapped_column(_JSON, default=dict)
    features: Mapped[dict] = mapped_column(_JSON, default=dict)


class Subscription(TimestampMixin, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        Index("ix_subscriptions_user_id", "user_id"),
        Index("ix_subscriptions_plan_id", "plan_id"),
        Index("ix_subscriptions_status", "status"),
        Index("ix_subscriptions_provider", "provider"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column()
    plan_id: Mapped[uuid.UUID] = mapped_column()
    provider: Mapped[str | None] = mapped_column(String(40))
    provider_customer_id: Mapped[str | None] = mapped_column(String(120))
    provider_subscription_id: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="active")
    billing_cycle: Mapped[str] = mapped_column(String(10), default="month")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BillingEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "billing_events"
    __table_args__ = (
        Index("ix_billing_events_user_id", "user_id"),
        Index("ix_billing_events_subscription_id", "subscription_id"),
        Index("ix_billing_events_provider", "provider"),
        Index("ix_billing_events_event_type", "event_type"),
        Index("ix_billing_events_created_at", "created_at"),
        UniqueConstraint("provider_event_id", name="uq_billing_events_provider_event_id"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column()
    subscription_id: Mapped[uuid.UUID | None] = mapped_column()
    provider: Mapped[str | None] = mapped_column(String(40))
    provider_event_id: Mapped[str | None] = mapped_column(String(120), unique=True)
    event_type: Mapped[str] = mapped_column(String(60))
    status: Mapped[str | None] = mapped_column(String(20))
    safe_metadata: Mapped[dict] = mapped_column(_JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
