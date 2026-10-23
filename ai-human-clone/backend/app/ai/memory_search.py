"""Semantic search over a clone's APPROVED long-term memories.

query -> embedding (the same service as knowledge search) -> Qdrant search in
the long-term memory collection, filtered by clone_id, owner_id and
status=approved -> memories at or above MEMORY_SCORE_THRESHOLD, best first.

Callers must have checked access; the ids always come from that check, never
from request data. Candidate, rejected and archived memories have no vectors,
and the status filter excludes them even if one were left behind.
"""

import logging
import uuid
from dataclasses import dataclass

from app.ai import embedding_service
from app.core.config import get_settings
from app.services import qdrant_service

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetrievedMemory:
    memory_id: uuid.UUID
    memory_type: str
    content: str
    score: float


def search_memories(
    clone_id: uuid.UUID,
    query: str,
    top_k: int | None = None,
    *,
    owner_id: uuid.UUID,
    min_score: float | None = None,
    memory_ids: list[uuid.UUID] | None = None,
) -> list[RetrievedMemory]:
    """Raises VectorStoreError / EmbeddingError if the search can't run.

    `memory_ids` restricts the search to those memories (the public ones for visitors).
    """
    settings = get_settings()
    limit = settings.memory_top_k if top_k is None else top_k
    threshold = settings.memory_score_threshold if min_score is None else min_score
    vector = embedding_service.get_embedding_service().embed_text(query)
    hits = qdrant_service.get_memory_store().search(
        clone_id=clone_id, owner_id=owner_id, vector=vector, limit=limit, min_score=threshold, memory_ids=memory_ids
    )
    memories = []
    for hit in hits:
        try:
            memory_id = uuid.UUID(hit.memory_id)
        except ValueError:
            continue
        memories.append(RetrievedMemory(memory_id, hit.memory_type, hit.content, hit.score))
    # Sizes and scores only, never memory content.
    logger.info(
        "Long-term memory search for clone %s: top_k=%d, threshold=%.2f, %d results%s",
        clone_id,
        limit,
        threshold,
        len(memories),
        f", best={memories[0].score:.3f}" if memories else "",
    )
    return memories
