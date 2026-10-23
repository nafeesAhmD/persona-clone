"""The only module that talks to Qdrant.

Two collections, never mixed:
- QDRANT_COLLECTION (default "clone_memories"): document knowledge chunks
  (QdrantService). Every point carries user_id, clone_id, document_id,
  chunk_index, source_type, title and text.
- QDRANT_MEMORY_COLLECTION (default "clone_long_term_memories"): approved
  long-term memories (LongTermMemoryStore), one point per memory, with
  owner_id, clone_id, memory_id, memory_type, content, status and created_at.
Their ids are indexed, so reads and deletes are always filtered, and search
requires a clone_id: there is no unfiltered search.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache

from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchAny,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

from app.core.config import get_settings

logger = logging.getLogger(__name__)

QDRANT_ERRORS = (ResponseHandlingException, UnexpectedResponse, ConnectionError, TimeoutError, OSError)
INDEXED_FIELDS = ("clone_id", "document_id", "user_id")
MEMORY_INDEXED_FIELDS = ("clone_id", "owner_id", "memory_id", "status")
# Fixed namespace so a (document, chunk) pair always maps to the same point id.
_POINT_NAMESPACE = uuid.UUID("5b0f6c1e-3f7a-4a51-9c8e-6f2d7a1b9e40")


class VectorStoreError(Exception):
    """Qdrant is unreachable or rejected an operation (mapped to HTTP 503)."""


@dataclass(frozen=True)
class ChunkRecord:
    """One chunk to store, with the ids that tie it back to PostgreSQL."""

    user_id: uuid.UUID
    clone_id: uuid.UUID
    document_id: uuid.UUID
    chunk_index: int
    source_type: str
    title: str
    text: str


@dataclass(frozen=True)
class MemoryHit:
    score: float
    document_id: str
    chunk_index: int
    title: str
    source_type: str
    text: str


def point_id(document_id: uuid.UUID, chunk_index: int) -> str:
    """Stable UUID per chunk: re-indexing overwrites instead of duplicating."""
    return str(uuid.uuid5(_POINT_NAMESPACE, f"{document_id}:{chunk_index}"))


def _ensure_collection(client: QdrantClient, name: str, vector_size: int, indexed_fields: tuple[str, ...]) -> None:
    """Create a cosine collection with keyword payload indexes, or check the existing one."""
    try:
        if not client.collection_exists(name):
            client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )
            logger.info("Created Qdrant collection %s (dim=%s, cosine)", name, vector_size)
        else:
            vectors = client.get_collection(name).config.params.vectors
            existing = vectors.size if isinstance(vectors, VectorParams) else None
            if existing is not None and existing != vector_size:
                raise VectorStoreError(
                    f"The collection {name} stores {existing}-dimensional vectors but the embedding "
                    f"model produces {vector_size}. Recreate the collection and reindex."
                )
        indexed = set((client.get_collection(name).payload_schema or {}).keys())
        for field in indexed_fields:
            if field not in indexed:
                client.create_payload_index(
                    collection_name=name, field_name=field, field_schema=PayloadSchemaType.KEYWORD
                )
    except QDRANT_ERRORS as exc:
        raise VectorStoreError("The memory store (Qdrant) is not available") from exc


def _match(*, any_of: tuple[str, list] | None = None, **conditions: uuid.UUID | str | None) -> Filter:
    """All conditions must match; `any_of=(key, values)` restricts `key` to an allowlist."""
    must = [
        FieldCondition(key=key, match=MatchValue(value=str(value)))
        for key, value in conditions.items()
        if value is not None
    ]
    if any_of is not None:
        key, values = any_of
        must.append(FieldCondition(key=key, match=MatchAny(any=[str(v) for v in values])))
    return Filter(must=must)


class QdrantService:
    def __init__(self, url: str, collection_name: str, api_key: str | None = None) -> None:
        self.collection_name = collection_name
        # ":memory:" runs an in-process Qdrant (used by the test suite).
        if url == ":memory:":
            self.client = QdrantClient(location=":memory:")
        else:
            self.client = QdrantClient(url=url, api_key=api_key, timeout=10)

    # --- Health / collection ----------------------------------------------

    def health_check(self) -> bool:
        try:
            self.client.get_collections()
            return True
        except QDRANT_ERRORS as exc:
            logger.warning("Qdrant unavailable: %s", exc)
            return False

    is_available = health_check  # older name used by /api/health/services

    def collection_exists(self) -> bool:
        return self.client.collection_exists(self.collection_name)

    def vector_size(self) -> int | None:
        if not self.collection_exists():
            return None
        vectors = self.client.get_collection(self.collection_name).config.params.vectors
        return vectors.size if isinstance(vectors, VectorParams) else None

    def ensure_collection(self, vector_size: int) -> None:
        """Create the collection (cosine distance) and payload indexes if missing.

        Raises VectorStoreError if an existing collection has a different vector
        size, which happens when EMBEDDING_MODEL changes; see README.
        """
        _ensure_collection(self.client, self.collection_name, vector_size, INDEXED_FIELDS)

    # --- Writes ---------------------------------------------------------

    def upsert_chunks(self, chunks: list[ChunkRecord], vectors: list[list[float]]) -> None:
        if not chunks:
            return
        points = [
            PointStruct(
                id=point_id(chunk.document_id, chunk.chunk_index),
                vector=vector,
                payload={
                    "user_id": str(chunk.user_id),
                    "clone_id": str(chunk.clone_id),
                    "document_id": str(chunk.document_id),
                    "chunk_index": chunk.chunk_index,
                    "source_type": chunk.source_type,
                    "title": chunk.title,
                    "text": chunk.text,
                },
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        try:
            self.client.upsert(collection_name=self.collection_name, points=points, wait=True)
        except QDRANT_ERRORS as exc:
            raise VectorStoreError("Could not store vectors in the memory store") from exc

    def _delete(self, selector: Filter) -> None:
        try:
            if not self.collection_exists():
                return
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=FilterSelector(filter=selector),
                wait=True,
            )
        except QDRANT_ERRORS as exc:
            raise VectorStoreError("Could not remove vectors from the memory store") from exc

    def delete_document_chunks(self, document_id: uuid.UUID) -> None:
        self._delete(_match(document_id=document_id))

    def delete_clone_chunks(self, clone_id: uuid.UUID) -> None:
        self._delete(_match(clone_id=clone_id))

    # --- Reads ----------------------------------------------------------

    def count_chunks(self, *, clone_id: uuid.UUID, document_id: uuid.UUID | None = None) -> int:
        try:
            if not self.collection_exists():
                return 0
            return self.client.count(
                collection_name=self.collection_name,
                count_filter=_match(clone_id=clone_id, document_id=document_id),
                exact=True,
            ).count
        except QDRANT_ERRORS as exc:
            raise VectorStoreError("The memory store (Qdrant) is not available") from exc

    def search_similar_chunks(
        self,
        *,
        clone_id: uuid.UUID,
        vector: list[float],
        limit: int,
        min_score: float = 0.0,
        document_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        document_ids: list[uuid.UUID] | None = None,
    ) -> list[MemoryHit]:
        """Nearest chunks of ONE clone (clone_id is mandatory), best first.

        `document_ids` limits the search to those documents (public clone search
        passes the clone's public documents); an empty list finds nothing.
        """
        if document_ids is not None and not document_ids:
            return []
        try:
            if not self.collection_exists():
                return []
            result = self.client.query_points(
                collection_name=self.collection_name,
                query=vector,
                query_filter=_match(
                    clone_id=clone_id,
                    document_id=document_id,
                    user_id=user_id,
                    any_of=("document_id", document_ids) if document_ids is not None else None,
                ),
                limit=limit,
                score_threshold=min_score,
                with_payload=True,
            )
        except QDRANT_ERRORS as exc:
            raise VectorStoreError("The memory store (Qdrant) is not available") from exc

        allowed = {str(d) for d in document_ids} if document_ids is not None else None
        hits = []
        for point in result.points:
            payload = point.payload or {}
            if payload.get("clone_id") != str(clone_id):  # defence in depth
                continue
            if allowed is not None and payload.get("document_id") not in allowed:
                continue
            hits.append(
                MemoryHit(
                    score=point.score,
                    document_id=payload.get("document_id", ""),
                    chunk_index=int(payload.get("chunk_index", 0)),
                    # "filename" is the payload key used before titles existed.
                    title=payload.get("title") or payload.get("filename") or "Untitled",
                    source_type=payload.get("source_type", "file"),
                    text=payload.get("text", ""),
                )
            )
        return hits


# --- Long-term memories -------------------------------------------------------


@dataclass(frozen=True)
class MemoryVector:
    """One approved memory to store; the point id is the memory id."""

    memory_id: uuid.UUID
    owner_id: uuid.UUID
    clone_id: uuid.UUID
    memory_type: str
    content: str
    status: str
    created_at: datetime


@dataclass(frozen=True)
class MemoryVectorHit:
    score: float
    memory_id: str
    memory_type: str
    content: str


class LongTermMemoryStore:
    """Vectors of approved long-term memories, in their own collection.

    Shares the knowledge store's client (one connection pool, and the same
    in-process engine in tests).
    """

    def __init__(self, client: QdrantClient, collection_name: str) -> None:
        self.client = client
        self.collection_name = collection_name

    def ensure_collection(self, vector_size: int) -> None:
        _ensure_collection(self.client, self.collection_name, vector_size, MEMORY_INDEXED_FIELDS)

    def upsert_memory(self, memory: MemoryVector, vector: list[float]) -> None:
        """Store or replace (same point id) the vector of one memory."""
        point = PointStruct(
            id=str(memory.memory_id),
            vector=vector,
            payload={
                "owner_id": str(memory.owner_id),
                "clone_id": str(memory.clone_id),
                "memory_id": str(memory.memory_id),
                "memory_type": memory.memory_type,
                "content": memory.content,
                "status": memory.status,
                "created_at": memory.created_at.isoformat(),
            },
        )
        try:
            self.client.upsert(collection_name=self.collection_name, points=[point], wait=True)
        except QDRANT_ERRORS as exc:
            raise VectorStoreError("Could not store the memory in the memory store") from exc

    def _delete(self, selector: Filter) -> None:
        try:
            if not self.client.collection_exists(self.collection_name):
                return
            self.client.delete(
                collection_name=self.collection_name, points_selector=FilterSelector(filter=selector), wait=True
            )
        except QDRANT_ERRORS as exc:
            raise VectorStoreError("Could not remove memories from the memory store") from exc

    def delete_memory(self, memory_id: uuid.UUID) -> None:
        self._delete(_match(memory_id=memory_id))

    def delete_clone_memories(self, clone_id: uuid.UUID) -> None:
        self._delete(_match(clone_id=clone_id))

    def count(self, *, clone_id: uuid.UUID, memory_id: uuid.UUID | None = None) -> int:
        try:
            if not self.client.collection_exists(self.collection_name):
                return 0
            return self.client.count(
                collection_name=self.collection_name,
                count_filter=_match(clone_id=clone_id, memory_id=memory_id),
                exact=True,
            ).count
        except QDRANT_ERRORS as exc:
            raise VectorStoreError("The memory store (Qdrant) is not available") from exc

    def search(
        self,
        *,
        clone_id: uuid.UUID,
        owner_id: uuid.UUID,
        vector: list[float],
        limit: int,
        min_score: float,
        memory_ids: list[uuid.UUID] | None = None,
    ) -> list[MemoryVectorHit]:
        """Nearest APPROVED memories of one clone and owner, best first.

        `memory_ids` limits the search to those memories (the public ones for
        visitors); an empty list finds nothing.
        """
        if memory_ids is not None and not memory_ids:
            return []
        try:
            if not self.client.collection_exists(self.collection_name):
                return []
            result = self.client.query_points(
                collection_name=self.collection_name,
                query=vector,
                query_filter=_match(
                    clone_id=clone_id,
                    owner_id=owner_id,
                    status="approved",
                    any_of=("memory_id", memory_ids) if memory_ids is not None else None,
                ),
                limit=limit,
                score_threshold=min_score,
                with_payload=True,
            )
        except QDRANT_ERRORS as exc:
            raise VectorStoreError("The memory store (Qdrant) is not available") from exc

        hits = []
        for point in result.points:
            payload = point.payload or {}
            if (
                payload.get("clone_id") != str(clone_id)
                or payload.get("owner_id") != str(owner_id)
                or payload.get("status") != "approved"
            ):  # defence in depth
                continue
            hits.append(
                MemoryVectorHit(
                    score=point.score,
                    memory_id=payload.get("memory_id", ""),
                    memory_type=payload.get("memory_type", "other"),
                    content=payload.get("content", ""),
                )
            )
        return hits


def get_memory_store() -> LongTermMemoryStore:
    return LongTermMemoryStore(get_qdrant_service().client, get_settings().qdrant_memory_collection)


@lru_cache
def get_qdrant_service() -> QdrantService:
    settings = get_settings()
    return QdrantService(
        url=settings.qdrant_url,
        collection_name=settings.qdrant_collection,
        api_key=settings.qdrant_api_key,
    )
