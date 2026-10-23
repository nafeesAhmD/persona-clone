"""Phase 18 marketplace: saved (favorite) clones and reports about public clones."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin

REPORT_REASONS = (
    "impersonation",
    "unauthorized_voice_or_avatar",
    "privacy",
    "harmful_or_misleading",
    "spam",
    "other",
)
REPORT_STATUSES = ("open", "reviewing", "resolved", "dismissed")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class FavoriteClone(UUIDPrimaryKeyMixin, Base):
    """A clone a user saved to their library. One row per user and clone."""

    __tablename__ = "favorite_clones"
    __table_args__ = (
        UniqueConstraint("user_id", "clone_id", name="uq_favorite_clones_user_clone"),
        Index("ix_favorite_clones_clone_id", "clone_id"),
        Index("ix_favorite_clones_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    clone_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clone_profiles.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CloneReport(UUIDPrimaryKeyMixin, Base):
    """A report about a public clone. Anonymous reporters are kept only as a hash of their
    address (for de-duplication and rate limits). resolution_note is for administrators only."""

    __tablename__ = "clone_reports"
    __table_args__ = (
        CheckConstraint(_in("reason", REPORT_REASONS), name="ck_clone_reports_reason"),
        CheckConstraint(_in("status", REPORT_STATUSES), name="ck_clone_reports_status"),
        Index("ix_clone_reports_clone_id", "clone_id"),
        Index("ix_clone_reports_status_created", "status", "created_at"),
    )

    reporter_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reporter_key: Mapped[str | None] = mapped_column(String(64))
    clone_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clone_profiles.id", ondelete="CASCADE"))
    reason: Mapped[str] = mapped_column(String(40))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="open", server_default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    resolution_note: Mapped[str | None] = mapped_column(String(500))
