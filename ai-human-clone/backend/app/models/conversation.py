import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.clone_profile import CloneProfile
    from app.models.message import Message


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A chat between one user and one clone. Only that user can read or delete it."""

    __tablename__ = "conversations"
    __table_args__ = (
        # The sidebar query: "this user's conversations with this clone, newest first".
        Index("ix_conversations_user_clone_updated", "user_id", "clone_id", "updated_at"),
    )

    clone_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clone_profiles.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str | None] = mapped_column(String(255))
    # Where it was started: "app" (the website) or "api" (the developer API, Phase 14).
    source: Mapped[str] = mapped_column(String(10), default="app", server_default="app")

    clone: Mapped["CloneProfile"] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )
