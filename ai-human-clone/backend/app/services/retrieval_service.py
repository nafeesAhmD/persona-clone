"""Semantic search over one clone's AI memory.

query -> embedding -> Qdrant similarity search filtered by clone_id -> chunks
at or above MIN_SIMILARITY_SCORE, best first. Callers must have checked that
the user may access the clone; the clone id always comes from that check,
never from request data.

Used by the "Test AI Memory" search API, and it is the retrieval step the
Phase 5 answer generation builds on.
"""

import logging
import uuid

from app.ai import embedding_service
from app.core.config import get_settings
from app.models import CloneProfile
from app.services import qdrant_service
from app.services.qdrant_service import MemoryHit

logger = logging.getLogger(__name__)


def search_knowledge(
    clone: CloneProfile,
    query: str,
    top_k: int,
    *,
    min_score: float | None = None,
    document_id: uuid.UUID | None = None,
    document_ids: list[uuid.UUID] | None = None,
) -> list[MemoryHit]:
    """`document_ids` restricts the search to those documents (e.g. the public ones)."""
    settings = get_settings()
    threshold = settings.min_similarity_score if min_score is None else min_score
    vector = embedding_service.get_embedding_service().embed_text(query)
    hits = qdrant_service.get_qdrant_service().search_similar_chunks(
        clone_id=clone.id,
        vector=vector,
        limit=top_k,
        min_score=threshold,
        document_id=document_id,
        document_ids=document_ids,
    )
    # Log sizes and scores only, never the query or document text.
    logger.info(
        "Memory search for clone %s: top_k=%d, threshold=%.2f, %d results%s",
        clone.id,
        top_k,
        threshold,
        len(hits),
        f", best={hits[0].score:.3f}" if hits else "",
    )
    return hits
