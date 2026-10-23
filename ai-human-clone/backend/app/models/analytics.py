"""Analytics event model for Phase 11."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin

_JSON = JSON().with_variant(JSONB(), "postgresql")


class AnalyticsEvent(UUIDPrimaryKeyMixin, Base):
    """Analytics event for clone usage tracking."""

    __tablename__ = "analytics_events"
    __table_args__ = (
        Index("ix_analytics_events_clone_id", "clone_id"),
        Index("ix_analytics_events_user_id", "user_id"),
        Index("ix_analytics_events_event_type", "event_type"),
        Index("ix_analytics_events_created_at", "created_at"),
        Index("ix_analytics_events_session_id", "session_id"),
        Index("ix_analytics_events_clone_created", "clone_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column()
    clone_id: Mapped[uuid.UUID | None] = mapped_column()
    session_id: Mapped[str | None] = mapped_column(String(100))
    event_type: Mapped[str] = mapped_column(String(40))
    source: Mapped[str | None] = mapped_column(String(40))
    metadata: Mapped[dict] = mapped_column(_JSON, default=dict)
    duration_ms: Mapped[float | None] = mapped_column(Float)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
