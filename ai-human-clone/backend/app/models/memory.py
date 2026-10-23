import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.clone_profile import CloneProfile

# Allowed values, shared with the API schemas and the migration.
MEMORY_TYPES = (
    "fact",
    "preference",
    "communication_preference",
    "skill",
    "experience",
    "project",
    "goal",
    "background",
    "instruction",
    "other",
)
MEMORY_STATUSES = ("candidate", "approved", "rejected", "archived")
MEMORY_SOURCES = ("conversation", "manual")
MEMORY_VISIBILITIES = ("private", "public")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class CloneMemory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A long-term memory of one clone, owned by the clone's owner.

    Lifecycle: candidate (AI-suggested) -> approved (used in chat) or rejected;
    approved memories can be archived. Manual memories start approved. Only
    approved memories have a vector in Qdrant (`indexed_at` is set while they do).
    """

    __tablename__ = "clone_memories"
    __table_args__ = (
        CheckConstraint(_in("memory_type", MEMORY_TYPES), name="ck_clone_memories_memory_type"),
        CheckConstraint(_in("status", MEMORY_STATUSES), name="ck_clone_memories_status"),
        CheckConstraint(_in("source", MEMORY_SOURCES), name="ck_clone_memories_source"),
        CheckConstraint(_in("visibility", MEMORY_VISIBILITIES), name="ck_clone_memories_visibility"),
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="ck_clone_memories_confidence"),
        # The memory page: "this clone's memories with this status, newest first".
        Index("ix_clone_memories_clone_status_created", "clone_id", "status", "created_at"),
        Index("ix_clone_memories_created_at", "created_at"),
    )

    clone_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clone_profiles.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    memory_type: Mapped[str] = mapped_column(String(40), index=True)
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20))
    # The conversation a suggestion came from; kept (as NULL) if that conversation is deleted.
    source_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), index=True
    )
    confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), index=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # "public": usable when visitors chat with the public clone (only if also approved).
    visibility: Mapped[str] = mapped_column(String(10), default="private", server_default="private", index=True)

    clone: Mapped["CloneProfile"] = relationship(back_populates="memories")
