"""RAG for public clone visitors: only content the owner marked public.

visitor question
  -> public scope (from PostgreSQL): the clone's documents with visibility=public
     that are ready and indexed, and its memories that are approved AND public
  -> knowledge search restricted to those document ids (Qdrant MatchAny filter,
     always together with clone_id) + memory search restricted to those memory ids
  -> found memories re-checked against the database
  -> public system prompt (public_clone_prompt.py) with PUBLIC_* limits
  -> LLM (the same provider and client as private chat)

The allowlists come from the database at request time, so marking something
private takes effect immediately and nothing depends on Qdrant payloads. With
no public content the search returns nothing (it never widens to everything).
"""

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import factory, rag_pipeline
from app.ai.base import ChatTurn, GenerationOptions
from app.ai.memory_search import RetrievedMemory
from app.ai.public_clone_prompt import build_public_system_prompt
from app.ai.rag_context import RagContext
from app.ai.rag_pipeline import CloneReply, PreparedPrompt
from app.core.config import get_settings
from app.models import CloneMemory, CloneProfile, Document

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PublicScope:
    document_ids: list[uuid.UUID]
    memory_ids: list[uuid.UUID]


def public_scope(db: Session, clone: CloneProfile) -> PublicScope:
    documents = db.scalars(
        select(Document.id).where(
            Document.clone_id == clone.id,
            Document.owner_id == clone.owner_id,
            Document.visibility == "public",
            Document.status == "ready",
            Document.indexing_status == "indexed",
        )
    )
    memories = db.scalars(
        select(CloneMemory.id).where(
            CloneMemory.clone_id == clone.id,
            CloneMemory.owner_id == clone.owner_id,
            CloneMemory.status == "approved",
            CloneMemory.visibility == "public",
        )
    )
    return PublicScope(document_ids=list(documents), memory_ids=list(memories))


def confirm_public_memories(db: Session, clone: CloneProfile, found: list[RetrievedMemory]) -> list[RetrievedMemory]:
    """Keep only memories that are still approved and public, with their stored text."""
    if not found:
        return []
    rows = {
        memory.id: memory
        for memory in db.scalars(
            select(CloneMemory).where(
                CloneMemory.id.in_([m.memory_id for m in found]),
                CloneMemory.clone_id == clone.id,
                CloneMemory.status == "approved",
                CloneMemory.visibility == "public",
            )
        )
    }
    return [
        RetrievedMemory(m.memory_id, rows[m.memory_id].memory_type, rows[m.memory_id].content, m.score)
        for m in found
        if m.memory_id in rows
    ]


def retrieve_public_context(db: Session, clone: CloneProfile, question: str) -> RagContext:
    """Sync (DB + CPU + Qdrant). Raises VectorStoreError/EmbeddingError like private chat."""
    settings = get_settings()
    scope = public_scope(db, clone)
    context = rag_pipeline.retrieve_context(
        clone,
        question,
        include_memory=bool(scope.memory_ids),
        memory_filter=lambda found: confirm_public_memories(db, clone, found),
        document_ids=scope.document_ids,
        memory_ids=scope.memory_ids,
        top_k=settings.public_rag_top_k,
        max_chars=settings.public_rag_max_context_chars,
    )
    logger.info(
        "Public RAG for clone %s: %d public documents, %d public memories in scope",
        clone.id,
        len(scope.document_ids),
        len(scope.memory_ids),
    )
    return context


def public_options() -> GenerationOptions:
    settings = get_settings()
    return GenerationOptions(
        max_tokens=settings.public_max_output_tokens,
        model=settings.public_claude_model.strip() or None,
        model_provider="claude",
    )


def prepare_public_prompt(
    clone: CloneProfile, message: str, context: RagContext, history: list[ChatTurn] | None = None
) -> PreparedPrompt:
    return PreparedPrompt(
        system_prompt=build_public_system_prompt(clone),
        user_message=message,
        context=context,
        history=list(history or []),
        options=public_options(),
        clone_id=clone.id,
    )


async def generate_public_response(
    clone: CloneProfile, message: str, context: RagContext, history: list[ChatTurn] | None = None
) -> CloneReply:
    return await rag_pipeline.answer(clone, prepare_public_prompt(clone, message, context, history))


def active_model_name() -> str:
    options = public_options()
    provider = factory.get_llm_provider()
    return options.model_for(provider.name) or provider.model_name
