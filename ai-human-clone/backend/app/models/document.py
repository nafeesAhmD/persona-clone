import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, deferred, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.clone_profile import CloneProfile

SOURCE_TYPES = ("file", "manual_text")
DOCUMENT_STATUSES = ("pending", "processing", "ready", "failed")
FILE_TYPES = ("pdf", "docx", "txt", "md")
INDEXING_STATUSES = ("not_indexed", "indexing", "indexed", "indexing_failed")
VISIBILITIES = ("private", "public")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One knowledge source of a clone: an uploaded file or manually written text."""

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(_in("source_type", SOURCE_TYPES), name="ck_documents_source_type"),
        CheckConstraint(_in("status", DOCUMENT_STATUSES), name="ck_documents_status"),
        CheckConstraint(f"file_type IS NULL OR {_in('file_type', FILE_TYPES)}", name="ck_documents_file_type"),
        CheckConstraint(_in("indexing_status", INDEXING_STATUSES), name="ck_documents_indexing_status"),
        CheckConstraint(_in("visibility", VISIBILITIES), name="ck_documents_visibility"),
        # Public clone search: "this clone's public documents".
        Index("ix_documents_clone_visibility", "clone_id", "visibility"),
        # The knowledge list is always "this clone's documents, newest first".
        Index("ix_documents_clone_id_created_at", "clone_id", "created_at"),
    )

    clone_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clone_profiles.id", ondelete="CASCADE"), index=True
    )
    # Denormalised from the clone so ownership checks and per-user queries are direct.
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")

    # File uploads only. stored_filename is a generated name ("<uuid>.pdf"),
    # never the user's filename, and is never returned by the API.
    original_filename: Mapped[str | None] = mapped_column(String(255))
    stored_filename: Mapped[str | None] = mapped_column(String(64))
    file_type: Mapped[str | None] = mapped_column(String(10))
    mime_type: Mapped[str | None] = mapped_column(String(120))
    file_size: Mapped[int | None] = mapped_column(BigInteger)

    # Loaded only when accessed, so listing documents never pulls large texts.
    extracted_text: Mapped[str | None] = deferred(mapped_column(Text))
    character_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # A short, user-safe explanation when processing fails (never a stack trace).
    error_message: Mapped[str | None] = mapped_column(String(500))

    # AI memory (vector index), tracked separately from text extraction above:
    # a document can be status="ready" and indexing_status="indexing_failed".
    indexing_status: Mapped[str] = mapped_column(String(20), default="not_indexed", server_default="not_indexed")
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    indexing_error: Mapped[str | None] = mapped_column(String(500))
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # "public": visitors of the public clone may get answers from it. Private by default.
    visibility: Mapped[str] = mapped_column(String(10), default="private", server_default="private")

    clone: Mapped["CloneProfile"] = relationship(back_populates="documents")
