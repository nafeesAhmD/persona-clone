"""Turns a document's extracted text into AI memory (vectors in Qdrant).

Pipeline: extracted_text -> text_chunker -> embedding_service -> qdrant_service,
with the outcome recorded on the Document (indexing_status, indexed_at,
indexing_error, chunk_count). Extraction status (`status`) is never touched here.

Indexing always deletes the document's previous vectors first and point ids are
deterministic per (document, chunk), so repeating it never duplicates chunks.
If embedding or storing fails, the document is marked indexing_failed and any
partially written vectors are removed: the database never says "indexed" for
vectors that aren't there.

Runs synchronously for now; index_document() is the single entry point a
background job would call later.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.ai import embedding_service
from app.ai.embedding_service import EmbeddingError
from app.core.config import get_settings
from app.models import Document
from app.services import qdrant_service
from app.services.errors import InvalidInputError
from app.services.qdrant_service import ChunkRecord, VectorStoreError
from app.services.text_chunker import ChunkingConfig, chunk_text

logger = logging.getLogger(__name__)

_EMBED_BATCH = 64


def chunking_config() -> ChunkingConfig:
    settings = get_settings()
    return ChunkingConfig(chunk_size=settings.chunk_size, overlap=settings.chunk_overlap)


def build_chunks(document: Document, text: str) -> list[ChunkRecord]:
    return [
        ChunkRecord(
            user_id=document.owner_id,
            clone_id=document.clone_id,
            document_id=document.id,
            chunk_index=index,
            source_type=document.source_type,
            title=document.title,
            text=chunk,
        )
        for index, chunk in enumerate(chunk_text(text, chunking_config()))
    ]


def _fail(db: Session, document: Document, message: str) -> Document:
    document.indexing_status = "indexing_failed"
    document.indexing_error = message[:500]
    document.chunk_count = 0
    document.indexed_at = None
    db.commit()
    return document


def index_document(db: Session, document: Document) -> Document:
    """(Re)build the document's vectors. Never raises for embedding/Qdrant failures."""
    if document.status != "ready":
        raise InvalidInputError("Only documents whose text is ready can be indexed.")
    text = document.extracted_text
    if not text:
        raise InvalidInputError("This document has no stored text. Upload the file again to index it.")

    embedder = embedding_service.get_embedding_service()
    store = qdrant_service.get_qdrant_service()

    document.indexing_status = "indexing"
    document.indexing_error = None
    db.commit()
    logger.info("Indexing started for document %s (clone %s, %d characters)", document.id, document.clone_id, len(text))

    chunks = build_chunks(document, text)
    try:
        vectors: list[list[float]] = []
        for start in range(0, len(chunks), _EMBED_BATCH):
            vectors.extend(embedder.embed_documents([c.text for c in chunks[start : start + _EMBED_BATCH]]))
    except EmbeddingError as exc:
        logger.error("Indexing failed for document %s: embedding error: %s", document.id, exc)
        return _fail(db, document, f"Embedding failed: {exc}")

    try:
        store.ensure_collection(embedder.dimension)
        store.delete_document_chunks(document.id)  # replace, never append
        store.upsert_chunks(chunks, vectors)
    except VectorStoreError as exc:
        logger.error("Indexing failed for document %s: vector store error: %s", document.id, exc)
        try:
            store.delete_document_chunks(document.id)  # clean up a partial write
        except VectorStoreError:
            logger.warning("Could not clean up partial vectors of document %s", document.id)
        return _fail(db, document, str(exc))

    document.indexing_status = "indexed"
    document.indexed_at = datetime.now(UTC)
    document.chunk_count = len(chunks)
    db.commit()
    logger.info("Indexing completed for document %s: %d chunks", document.id, len(chunks))
    return document


def remove_document_vectors(document: Document) -> None:
    """Delete a document's vectors. Raises VectorStoreError so callers can stop
    before deleting the database row (no orphaned vectors)."""
    qdrant_service.get_qdrant_service().delete_document_chunks(document.id)


def mark_not_indexed(db: Session, document: Document) -> None:
    """After the text changed (e.g. failed re-extraction): old vectors must go."""
    try:
        remove_document_vectors(document)
    except VectorStoreError:
        logger.warning("Could not remove stale vectors of document %s", document.id)
    document.indexing_status = "not_indexed"
    document.indexed_at = None
    document.chunk_count = 0
    db.commit()
