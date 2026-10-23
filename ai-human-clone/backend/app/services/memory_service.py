"""Long-term memories of a clone: lifecycle, ownership, vectors and extraction.

Lifecycle:  conversation -> candidate (AI suggestion) -> approved | rejected
            manual memory -> approved;  approved -> archived (or back)
Only approved memories have a vector (QDRANT_MEMORY_COLLECTION) and reach chat.

Access: callers load the clone with clone_service.get_managed_clone (owner
only); every memory lookup here then also checks that the memory belongs to
that clone AND that user, so ids from another clone or user are a 404.

Vectors and rows stay in step: the vector change happens first and the row is
committed after it. If Qdrant or the embedding model fails, the row change is
rolled back (HTTP 503) so the database never claims a state the vectors don't
match. Chat additionally re-checks each found memory against the database.
"""

import logging
import math
import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.ai import embedding_service
from app.ai.embedding_service import EmbeddingError
from app.ai.memory_extractor import ExtractedMemory, build_transcript, extract_memories
from app.ai.memory_search import RetrievedMemory
from app.core.config import get_settings
from app.models import CloneMemory, CloneProfile, Conversation, User
from app.schemas.memory import ExtractionSkipped, MemoryCreate, MemoryUpdate
from app.services import conversation_service, qdrant_service
from app.services.errors import ConflictError, InvalidInputError, NotFoundError
from app.services.memory_safety import looks_sensitive
from app.services.qdrant_service import MemoryVector

logger = logging.getLogger(__name__)

NOT_FOUND = "Memory not found"
SENSITIVE = "This looks like a password, key, card number or other secret. Secrets can't be stored as memories."
DUPLICATE = "A memory with the same meaning already exists."
_DEDUPE_POOL = 500  # most recent memories compared against new ones
_PROMPT_KNOWN = 100  # most recent memories shown to the extractor


def _now() -> datetime:
    return datetime.now(UTC)


# --- Lookups --------------------------------------------------------------------


def get_memory(db: Session, clone: CloneProfile, user: User, memory_id: uuid.UUID) -> CloneMemory:
    memory = db.get(CloneMemory, memory_id)
    if memory is None or memory.clone_id != clone.id or memory.owner_id != user.id:
        raise NotFoundError(NOT_FOUND)
    return memory


def list_memories(
    db: Session, clone: CloneProfile, user: User, *, status: str | None = None, memory_type: str | None = None
) -> list[CloneMemory]:
    query = select(CloneMemory).where(CloneMemory.clone_id == clone.id, CloneMemory.owner_id == user.id)
    if status:
        query = query.where(CloneMemory.status == status)
    if memory_type:
        query = query.where(CloneMemory.memory_type == memory_type)
    return list(db.scalars(query.order_by(CloneMemory.created_at.desc(), CloneMemory.id)))


# --- Vectors --------------------------------------------------------------------


def _sync_vector(memory: CloneMemory) -> None:
    """Approved: (re)write its vector. Anything else: make sure it has none."""
    store = qdrant_service.get_memory_store()
    if memory.status == "approved":
        embedder = embedding_service.get_embedding_service()
        vector = embedder.embed_text(memory.content)
        store.ensure_collection(embedder.dimension)
        store.upsert_memory(
            MemoryVector(
                memory_id=memory.id,
                owner_id=memory.owner_id,
                clone_id=memory.clone_id,
                memory_type=memory.memory_type,
                content=memory.content,
                status=memory.status,
                created_at=memory.created_at,
            ),
            vector,
        )
        memory.indexed_at = _now()
    else:
        store.delete_memory(memory.id)
        memory.indexed_at = None


def _save(db: Session, memory: CloneMemory) -> CloneMemory:
    """Bring the vector in line with the memory, then commit; undo the row change on failure."""
    memory_id = memory.id  # read before a rollback expires or detaches the object
    try:
        _sync_vector(memory)
        db.commit()
    except Exception:
        db.rollback()
        _resync_after_failure(db, memory_id)
        raise
    db.refresh(memory)
    return memory


def _resync_after_failure(db: Session, memory_id: uuid.UUID) -> None:
    # The vector may already have changed; put it back in line with the stored row.
    try:
        stored = db.get(CloneMemory, memory_id)
        if stored is None:
            qdrant_service.get_memory_store().delete_memory(memory_id)
        else:
            _sync_vector(stored)
            db.commit()
    except Exception as exc:  # noqa: BLE001 - best effort; chat re-checks rows anyway
        db.rollback()
        logger.warning("Could not resync the vector of memory %s: %s", memory_id, exc)


# --- Duplicates -----------------------------------------------------------------


def _normalise(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norms = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norms if norms else 0.0


class DuplicateFinder:
    """Same fact = same normalised text, or embeddings at least MEMORY_DUPLICATE_THRESHOLD alike.

    Compares against the given memories and everything added since. If the
    embedding model is unavailable, falls back to text comparison only.
    """

    def __init__(self, existing: Sequence[str]) -> None:
        self.threshold = get_settings().memory_duplicate_threshold
        self.texts = {_normalise(text) for text in existing}
        self.vectors: list[list[float]] | None = []
        try:
            self.vectors = embedding_service.get_embedding_service().embed_documents(list(existing))
        except EmbeddingError as exc:
            logger.warning("Duplicate check without embeddings: %s", exc)
            self.vectors = None

    def _vector(self, text: str) -> list[float] | None:
        if self.vectors is None:
            return None
        try:
            return embedding_service.get_embedding_service().embed_text(text)
        except EmbeddingError:
            return None

    def check_and_add(self, text: str) -> bool:
        """True if `text` duplicates something known; otherwise remember it and return False."""
        normalised = _normalise(text)
        if normalised in self.texts:
            return True
        vector = self._vector(text)
        if vector is not None and any(_cosine(vector, known) >= self.threshold for known in self.vectors or []):
            return True
        self.texts.add(normalised)
        if vector is not None and self.vectors is not None:
            self.vectors.append(vector)
        return False


def _recent_contents(db: Session, clone: CloneProfile, statuses: Sequence[str], limit: int) -> list[str]:
    return list(
        db.scalars(
            select(CloneMemory.content)
            .where(CloneMemory.clone_id == clone.id, CloneMemory.status.in_(statuses))
            .order_by(CloneMemory.created_at.desc())
            .limit(limit)
        )
    )


# --- Owner actions --------------------------------------------------------------


def create_manual(db: Session, clone: CloneProfile, user: User, data: MemoryCreate) -> CloneMemory:
    """A memory the owner wrote: approved (and searchable) right away."""
    if looks_sensitive(data.content):
        raise InvalidInputError(SENSITIVE)
    if DuplicateFinder(_recent_contents(db, clone, ("approved", "candidate"), _DEDUPE_POOL)).check_and_add(
        data.content
    ):
        raise ConflictError(DUPLICATE)
    now = _now()
    memory = CloneMemory(
        clone_id=clone.id,
        owner_id=user.id,
        memory_type=data.memory_type,
        content=data.content,
        source="manual",
        confidence=1.0,
        status="approved",
        created_at=now,
        updated_at=now,
    )
    db.add(memory)
    db.flush()
    _save(db, memory)
    logger.info("User %s added memory %s to clone %s", user.id, memory.id, clone.id)
    return memory


def update_memory(db: Session, memory: CloneMemory, data: MemoryUpdate) -> CloneMemory:
    changes = data.model_dump(exclude_unset=True, exclude_none=True)
    if "content" in changes and looks_sensitive(changes["content"]):
        raise InvalidInputError(SENSITIVE)
    changed = {field: value for field, value in changes.items() if getattr(memory, field) != value}
    if not changed:
        return memory
    for field, value in changed.items():
        setattr(memory, field, value)
    memory.updated_at = _now()
    return _save(db, memory)


def approve(db: Session, memory: CloneMemory) -> CloneMemory:
    if memory.status == "approved":
        return memory
    memory.status = "approved"
    memory.updated_at = _now()
    return _save(db, memory)


def reject(db: Session, memory: CloneMemory) -> CloneMemory:
    if memory.status == "rejected":
        return memory
    if memory.status != "candidate":
        raise ConflictError("Only suggested memories can be rejected. Archive or delete this one instead.")
    memory.status = "rejected"
    memory.updated_at = _now()
    return _save(db, memory)


def delete_memory(db: Session, memory: CloneMemory) -> None:
    # Vector first: if Qdrant can't delete it (503), the row stays and can be deleted again.
    qdrant_service.get_memory_store().delete_memory(memory.id)
    db.delete(memory)
    db.commit()


def clear_memories(db: Session, clone: CloneProfile) -> int:
    """Delete every memory of this clone (rows and vectors). Documents, conversations
    and the clone itself are untouched."""
    qdrant_service.get_memory_store().delete_clone_memories(clone.id)
    deleted = db.execute(delete(CloneMemory).where(CloneMemory.clone_id == clone.id)).rowcount
    db.commit()
    logger.info("Cleared %d memories of clone %s", deleted, clone.id)
    return deleted


# --- Chat -----------------------------------------------------------------------


def confirm_for_chat(db: Session, clone: CloneProfile, found: list[RetrievedMemory]) -> list[RetrievedMemory]:
    """Keep only memories the database says are approved for this clone, with the
    stored text, and record that they were used."""
    if not found:
        return []
    rows = {
        memory.id: memory
        for memory in db.scalars(
            select(CloneMemory).where(
                CloneMemory.id.in_([m.memory_id for m in found]),
                CloneMemory.clone_id == clone.id,
                CloneMemory.owner_id == clone.owner_id,
                CloneMemory.status == "approved",
            )
        )
    }
    confirmed = [
        RetrievedMemory(m.memory_id, rows[m.memory_id].memory_type, rows[m.memory_id].content, m.score)
        for m in found
        if m.memory_id in rows
    ]
    if len(confirmed) < len(found):
        logger.warning("Ignored %d stale memory vectors for clone %s", len(found) - len(confirmed), clone.id)
    return confirmed


def mark_used(db: Session, memory_ids: Sequence[uuid.UUID]) -> None:
    if not memory_ids:
        return
    db.execute(update(CloneMemory).where(CloneMemory.id.in_(list(memory_ids))).values(last_used_at=_now()))
    db.commit()


# --- Extraction -----------------------------------------------------------------


class ExtractionOutcome:
    def __init__(self, candidates: list[CloneMemory], skipped: ExtractionSkipped, message: str) -> None:
        self.candidates = candidates
        self.skipped = skipped
        self.message = message


def extraction_input(db: Session, clone: CloneProfile, conversation: Conversation) -> tuple[str, list[str]]:
    """The transcript to analyse and the memories the extractor should not repeat."""
    settings = get_settings()
    messages = conversation_service.messages_of(db, conversation)
    if not any(message.role == "user" for message in messages):
        return "", []
    transcript = build_transcript(
        messages, settings.memory_extraction_max_messages, settings.memory_extraction_max_chars
    )
    known = _recent_contents(db, clone, ("approved", "candidate", "rejected"), _PROMPT_KNOWN)
    return transcript, known


def save_candidates(
    db: Session,
    clone: CloneProfile,
    user: User,
    conversation: Conversation,
    suggestions: list[ExtractedMemory],
    invalid: int,
) -> ExtractionOutcome:
    """Filter the model's suggestions and store the rest as candidates (never approved)."""
    settings = get_settings()
    skipped = ExtractionSkipped(invalid=invalid)
    # Rejected ones count too: a suggestion the owner turned down isn't offered again.
    finder = DuplicateFinder(_recent_contents(db, clone, ("approved", "candidate", "rejected", "archived"), _DEDUPE_POOL))
    candidates: list[CloneMemory] = []
    now = _now()
    for suggestion in sorted(suggestions, key=lambda s: s.confidence, reverse=True):
        if looks_sensitive(suggestion.content):
            skipped.sensitive += 1
            continue
        if finder.check_and_add(suggestion.content):
            skipped.duplicates += 1
            continue
        if len(candidates) >= settings.memory_extraction_max_candidates:
            break  # the most confident ones are kept
        memory = CloneMemory(
            clone_id=clone.id,
            owner_id=user.id,
            memory_type=suggestion.memory_type,
            content=suggestion.content,
            source="conversation",
            source_conversation_id=conversation.id,
            confidence=suggestion.confidence,
            status="candidate",
            created_at=now,
            updated_at=now,
        )
        db.add(memory)
        candidates.append(memory)
    db.commit()
    for memory in candidates:
        db.refresh(memory)
    if skipped.sensitive:
        logger.info("Dropped %d sensitive memory suggestions for clone %s", skipped.sensitive, clone.id)

    if candidates:
        message = f"Found {len(candidates)} possible {'memory' if len(candidates) == 1 else 'memories'}. Review them before they are used."
    elif suggestions and (skipped.duplicates or skipped.sensitive):
        message = "No new memories: everything found is already known or was not safe to store."
    else:
        message = "No new memories were found in this conversation."
    return ExtractionOutcome(candidates, skipped, message)


async def extract_from_conversation(
    db: Session, clone: CloneProfile, user: User, conversation: Conversation
) -> ExtractionOutcome:
    transcript, known = await run_in_threadpool(extraction_input, db, clone, conversation)
    if not transcript:
        return ExtractionOutcome([], ExtractionSkipped(), "There is nothing to learn from this conversation yet.")
    result = await extract_memories(transcript, known)
    return await run_in_threadpool(save_candidates, db, clone, user, conversation, result.memories, result.invalid)

