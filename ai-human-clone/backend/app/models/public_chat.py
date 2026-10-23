import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PublicChatSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An anonymous visitor's conversation with a public clone.

    The visitor holds a random token (secrets.token_urlsafe); only its SHA-256
    hash is stored, so a database leak doesn't reveal usable tokens. No account,
    email, IP address or other visitor data is kept.
    """

    __tablename__ = "public_chat_sessions"

    clone_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clone_profiles.id", ondelete="CASCADE"), index=True)
    session_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0)

    messages: Mapped[list["PublicChatMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="PublicChatMessage.created_at"
    )


class PublicChatMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "public_chat_messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="ck_public_chat_messages_role"),
        Index("ix_public_chat_messages_session_created", "session_id", "created_at"),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public_chat_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    input_mode: Mapped[str] = mapped_column(String(10), default="text", server_default="text")

    session: Mapped["PublicChatSession"] = relationship(back_populates="messages")
