import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.clone_profile import CloneProfile

AVATAR_TYPES = ("uploaded", "generated", "preset")
AVATAR_STATUSES = ("pending", "processing", "ready", "failed")
JOB_STATUSES = ("queued", "processing", "completed", "failed", "cancelled")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class CloneAvatar(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An avatar image of a clone. At most one per clone is active.

    The image file lives in storage/clones/{clone_id}/avatar/{image_path};
    image_path is a server-generated name, never the uploaded filename.
    The mouth position (relative 0..1 coordinates) drives the lip-sync.
    """

    __tablename__ = "clone_avatars"
    __table_args__ = (
        CheckConstraint(_in("avatar_type", AVATAR_TYPES), name="ck_clone_avatars_type"),
        CheckConstraint(_in("status", AVATAR_STATUSES), name="ck_clone_avatars_status"),
        Index("ix_clone_avatars_clone_active", "clone_id", "is_active"),
    )

    clone_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clone_profiles.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    image_path: Mapped[str] = mapped_column(String(64))
    avatar_type: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="ready")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    # Where the mouth is (fractions of width/height) and how wide it is (fraction of width).
    mouth_x: Mapped[float] = mapped_column(Float)
    mouth_y: Mapped[float] = mapped_column(Float)
    mouth_width: Mapped[float] = mapped_column(Float)
    face_detected: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    error_message: Mapped[str | None] = mapped_column(String(300))

    clone: Mapped["CloneProfile"] = relationship(back_populates="avatars")


class AvatarVideoJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One talking-avatar video: avatar image + the answer's speech -> MP4.

    Rendered in the background; the client polls the status. Files are kept
    outside the database: input_audio_path is a voice-storage id (Phase 7) and
    output_video_path a generated file name in storage/clones/{clone_id}/videos.
    """

    __tablename__ = "avatar_video_jobs"
    __table_args__ = (
        CheckConstraint(_in("status", JOB_STATUSES), name="ck_avatar_video_jobs_status"),
        CheckConstraint("progress >= 0 AND progress <= 100", name="ck_avatar_video_jobs_progress"),
        Index("ix_avatar_video_jobs_clone_created", "clone_id", "created_at"),
    )

    clone_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clone_profiles.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    # Videos for anonymous visitors of a public clone belong to their session instead.
    public_session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("public_chat_sessions.id", ondelete="CASCADE"), index=True
    )
    public_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("public_chat_messages.id", ondelete="CASCADE")
    )
    avatar_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clone_avatars.id", ondelete="SET NULL"))
    # What to say for test videos (answers use the message's text).
    text: Mapped[str | None] = mapped_column(Text)
    input_audio_path: Mapped[str | None] = mapped_column(String(64))
    output_video_path: Mapped[str | None] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(String(300))
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
