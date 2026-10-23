"""Knowledge sources for a clone: file uploads and manually written text.

Upload flow: validate name/type -> store under a generated name -> check the
bytes -> Document(pending) -> processing -> extract text -> ready | failed.
The extracted text is kept in PostgreSQL.

When text is ready it is indexed automatically (indexing_service); an
indexing failure is recorded in indexing_status and never undoes the saved text.
"""

import logging
import re
import uuid
from pathlib import PureWindowsPath
from typing import BinaryIO

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import CloneProfile, Document
from app.schemas.document import ManualKnowledgeCreate
from app.services.document_extractor import (
    ExtractionError,
    UnsupportedFileError,
    check_client_mime,
    extract_text,
    kind_for_type,
    kind_from_filename,
    verify_content,
)
from app.services.errors import InvalidInputError, NotFoundError
from app.services.file_storage import StorageError, get_file_storage
from app.services import indexing_service

logger = logging.getLogger(__name__)

NOT_FOUND = "Document not found"


class IngestionError(Exception):
    """The upload couldn't be stored (mapped to HTTP 502)."""


def _clean_filename(filename: str | None) -> str:
    """Display name only: basename, no control characters, bounded length."""
    # PureWindowsPath splits on both "/" and "\", so "..\\..\\x.pdf" -> "x.pdf".
    name = PureWindowsPath(filename or "").name
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    return (name or "upload")[:255]


def _default_title(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0].strip()
    return (stem or filename)[:255]


# --- Processing -------------------------------------------------------------


def _process(db: Session, document: Document) -> Document:
    """Extract text from the stored file and record the outcome. Never raises for bad files."""
    settings = get_settings()
    document.status = "processing"
    document.error_message = None
    db.commit()

    try:
        path = get_file_storage().local_path(document.clone_id, document.stored_filename or "")
        text = extract_text(
            path,
            kind_for_type(document.file_type),
            max_characters=settings.max_extracted_characters,
            max_pdf_pages=settings.max_pdf_pages,
        )
    except (ExtractionError, StorageError, UnsupportedFileError) as exc:
        document.status = "failed"
        document.extracted_text = None
        document.character_count = 0
        document.error_message = str(exc)[:500]
        db.commit()
        indexing_service.mark_not_indexed(db, document)  # no text -> no valid vectors
        logger.info("Extraction failed for document %s: %s", document.id, exc)
        return document

    document.extracted_text = text
    document.character_count = len(text)
    document.status = "ready"
    db.commit()
    return indexing_service.index_document(db, document)


# --- Public API -------------------------------------------------------------


def upload_file(
    db: Session,
    clone: CloneProfile,
    *,
    source: BinaryIO,
    filename: str | None,
    content_type: str | None,
    title: str | None,
) -> Document:
    settings = get_settings()
    original = _clean_filename(filename)
    try:
        kind = kind_from_filename(original)
        check_client_mime(kind, content_type)
    except UnsupportedFileError as exc:
        raise InvalidInputError(str(exc)) from exc

    storage = get_file_storage()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    try:
        stored_filename, size = storage.save(clone.id, source, kind.file_type, max_bytes)
    except StorageError as exc:
        raise IngestionError("Could not save the file. Please try again.") from exc

    try:
        verify_content(kind, storage.local_path(clone.id, stored_filename))
    except UnsupportedFileError as exc:
        storage.delete(clone.id, stored_filename)
        raise InvalidInputError(str(exc)) from exc

    document = Document(
        clone_id=clone.id,
        owner_id=clone.owner_id,  # from the clone, never from the request
        title=(title or "").strip()[:255] or _default_title(original),
        source_type="file",
        status="pending",
        original_filename=original,
        stored_filename=stored_filename,
        file_type=kind.file_type,
        mime_type=kind.mime_type,  # detected type, not the client's claim
        file_size=size,
    )
    db.add(document)
    db.commit()
    logger.info("Stored %s (%d bytes) for clone %s", document.id, size, clone.id)
    return _process(db, document)


def add_manual_knowledge(db: Session, clone: CloneProfile, data: ManualKnowledgeCreate) -> Document:
    document = Document(
        clone_id=clone.id,
        owner_id=clone.owner_id,
        title=data.title,
        source_type="manual_text",
        status="ready",
        extracted_text=data.content,
        character_count=len(data.content),
    )
    db.add(document)
    db.commit()
    return indexing_service.index_document(db, document)


def retry_document(db: Session, clone: CloneProfile, document_id: uuid.UUID) -> Document:
    document = get_document(db, clone, document_id)
    if document.source_type != "file" or not document.stored_filename:
        raise InvalidInputError("Only uploaded files can be processed again.")
    if document.status != "failed":
        raise InvalidInputError("Only failed documents can be retried.")
    return _process(db, document)


def list_documents(db: Session, clone: CloneProfile) -> list[Document]:
    return list(
        db.scalars(
            select(Document).where(Document.clone_id == clone.id).order_by(Document.created_at.desc())
        )
    )


def get_document(db: Session, clone: CloneProfile, document_id: uuid.UUID) -> Document:
    """A document of this clone. Callers must already have checked clone ownership."""
    document = db.get(Document, document_id)
    if document is None or document.clone_id != clone.id:
        raise NotFoundError(NOT_FOUND)
    return document


def delete_document(db: Session, clone: CloneProfile, document_id: uuid.UUID) -> None:
    """Remove vectors, then the stored file, then the record.

    If the vectors can't be removed (Qdrant down), nothing is deleted and
    VectorStoreError propagates (503), so no orphaned vectors are left behind.
    """
    document = get_document(db, clone, document_id)
    indexing_service.remove_document_vectors(document)
    if document.stored_filename:
        get_file_storage().delete(clone.id, document.stored_filename)
    db.delete(document)
    db.commit()
    logger.info("Deleted document %s from clone %s", document.id, clone.id)


def knowledge_stats(db: Session, clone_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, int]]:
    """Per clone: knowledge sources, indexed sources and memory chunks, in one
    grouped query (no N+1)."""
    if not clone_ids:
        return {}
    indexed = Document.indexing_status == "indexed"
    rows = db.execute(
        select(
            Document.clone_id,
            func.count(Document.id),
            func.sum(case((indexed, 1), else_=0)),
            func.sum(case((indexed, Document.chunk_count), else_=0)),
        )
        .where(Document.clone_id.in_(clone_ids))
        .group_by(Document.clone_id)
    ).all()
    return {
        clone_id: {"knowledge_count": total, "indexed_count": int(done or 0), "chunk_count": int(chunks or 0)}
        for clone_id, total, done, chunks in rows
    }
