"""Retrieval-augmented generation for clone chat.

question -> knowledge search (Qdrant, this clone only)
         + long-term memory search (approved memories; owner's own chats)
         -> reference block (rag_context) -> clone system prompt -> LLM -> answer.

This module knows nothing about HTTP or the database; chat_service handles
conversations and persistence around it.
"""

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

from starlette.concurrency import run_in_threadpool

from app.ai import factory, memory_search
from app.ai.base import ChatTurn, GenerationOptions, LLMTimeoutError
from app.ai.clone_prompt import build_clone_system_prompt
from app.ai.memory_search import RetrievedMemory
from app.ai.rag_context import RagContext, build_rag_context
from app.core.config import get_settings
from app.models import CloneProfile
from app.services import monitoring, retrieval_service

logger = logging.getLogger(__name__)


@dataclass
class CloneReply:
    text: str
    context: RagContext
    model_name: str
    latency_ms: int
    provider: str = ""


@dataclass
class PreparedPrompt:
    """Everything the LLM will receive for one turn."""

    system_prompt: str
    user_message: str
    context: RagContext
    history: list[ChatTurn] = field(default_factory=list)
    options: GenerationOptions | None = None  # e.g. shorter answers for public visitors
    clone_id: uuid.UUID | None = None  # for usage records only
    user_id: uuid.UUID | None = None


def _record_llm(prompt: PreparedPrompt, provider_name: str, output: str, started: float, status: str) -> None:
    """Usage only: estimated tokens and timing, never the prompt or the answer."""
    monitoring.usage(
        "LLM_REQUEST",
        provider=provider_name,
        status=status,
        user_id=prompt.user_id,
        clone_id=prompt.clone_id,
        input_units=monitoring.estimated_tokens(
            prompt.system_prompt, prompt.user_message, prompt.context.text, *(t["content"] for t in prompt.history)
        ),
        output_units=monitoring.estimated_tokens(output),
        duration_ms=int((time.monotonic() - started) * 1000),
    )


MemoryFilter = Callable[[list[RetrievedMemory]], list[RetrievedMemory]]


def _search_long_term_memory(
    clone: CloneProfile,
    question: str,
    memory_filter: MemoryFilter | None,
    memory_ids: list[uuid.UUID] | None = None,
) -> list[RetrievedMemory]:
    """Approved memories for this question, or none if the search fails: long-term
    memory is an extra, and chat must keep working from knowledge alone."""
    try:
        found = memory_search.search_memories(clone.id, question, owner_id=clone.owner_id, memory_ids=memory_ids)
        return memory_filter(found) if memory_filter else found
    except Exception as exc:  # noqa: BLE001 - any failure here must not break chat
        logger.warning("Long-term memory search failed for clone %s, answering without it: %s", clone.id, exc)
        return []


def retrieve_context(
    clone: CloneProfile,
    question: str,
    *,
    include_memory: bool = False,
    memory_filter: MemoryFilter | None = None,
    document_ids: list[uuid.UUID] | None = None,
    memory_ids: list[uuid.UUID] | None = None,
    top_k: int | None = None,
    max_chars: int | None = None,
) -> RagContext:
    """Search the clone's knowledge (and, if asked, its long-term memory) and build
    the reference block. Sync (CPU + Qdrant).

    Raises VectorStoreError / EmbeddingError if the knowledge can't be searched,
    so the caller doesn't answer as if the clone knew nothing. `memory_filter`
    lets the caller re-check found memories (e.g. against the database).
    `document_ids` / `memory_ids` restrict the search to allowlists (the public
    content, for visitors); top_k / max_chars override the private-chat limits.
    """
    settings = get_settings()
    hits = retrieval_service.search_knowledge(
        clone,
        question,
        top_k or settings.rag_top_k,
        min_score=settings.rag_score_threshold,
        document_ids=document_ids,
    )
    memories = _search_long_term_memory(clone, question, memory_filter, memory_ids) if include_memory else []
    context = build_rag_context(
        hits,
        max_chars or settings.rag_max_context_chars,
        memories=memories,
        memory_max_chars=min(settings.memory_max_context_chars, max_chars or settings.memory_max_context_chars),
    )
    logger.info(
        "RAG context for clone %s: %d of %d chunks, %d of %d memories, %d characters",
        clone.id,
        len(context.hits),
        len(hits),
        len(context.memories),
        len(memories),
        len(context.text) if context.has_knowledge or context.memories else 0,
    )
    return context


def prepare_prompt(
    clone: CloneProfile,
    user_message: str,
    context: RagContext,
    conversation_history: list[ChatTurn] | None = None,
    owner_name: str | None = None,
) -> PreparedPrompt:
    return PreparedPrompt(
        clone_id=clone.id,
        system_prompt=build_clone_system_prompt(clone, owner_name),
        user_message=user_message,
        context=context,
        history=list(conversation_history or []),
    )


async def generate_clone_response(
    clone: CloneProfile,
    user_message: str,
    conversation_history: list[ChatTurn] | None = None,
    *,
    context: RagContext | None = None,
    owner_name: str | None = None,
) -> CloneReply:
    """One complete answer. Pass `context` if it was already retrieved."""
    if context is None:
        context = await run_in_threadpool(retrieve_context, clone, user_message)
    return await answer(clone, prepare_prompt(clone, user_message, context, conversation_history, owner_name))


async def answer(clone: CloneProfile, prompt: PreparedPrompt) -> CloneReply:
    """Run a prepared prompt (private or public) within CHAT_RESPONSE_DEADLINE_SECONDS."""
    context = prompt.context
    provider = factory.get_llm_provider()
    started = time.monotonic()
    try:
        text = await asyncio.wait_for(
            provider.generate_response(
                system_prompt=prompt.system_prompt,
                user_message=prompt.user_message,
                context=prompt.context.text,
                history=prompt.history,
                options=prompt.options,
            ),
            timeout=get_settings().chat_response_deadline_seconds,
        )
    except TimeoutError as exc:
        _record_llm(prompt, provider.name, "", started, "failed")
        raise LLMTimeoutError("Answer exceeded CHAT_RESPONSE_DEADLINE_SECONDS") from exc
    except Exception:
        _record_llm(prompt, provider.name, "", started, "failed")
        raise
    _record_llm(prompt, provider.name, text, started, "success")
    latency_ms = int((time.monotonic() - started) * 1000)
    logger.info("Clone %s answered by %s in %d ms", clone.id, provider.model_name, latency_ms)
    return CloneReply(
        text=text, context=context, model_name=provider.model_name, latency_ms=latency_ms, provider=provider.name
    )


async def stream_clone_response(prompt: PreparedPrompt) -> AsyncIterator[str]:
    """The same answer, streamed piece by piece, within CHAT_RESPONSE_DEADLINE_SECONDS.

    The deadline covers the whole answer, including a provider's own retries,
    so a stalled model ends with LLMTimeoutError instead of an endless wait.
    """
    provider = factory.get_llm_provider()
    started = time.monotonic()
    deadline = started + get_settings().chat_response_deadline_seconds
    produced: list[str] = []
    status = "failed"
    stream = provider.stream_response(
        system_prompt=prompt.system_prompt,
        user_message=prompt.user_message,
        context=prompt.context.text,
        history=prompt.history,
        options=prompt.options,
    ).__aiter__()
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LLMTimeoutError("Streamed answer exceeded CHAT_RESPONSE_DEADLINE_SECONDS")
            try:
                piece = await asyncio.wait_for(stream.__anext__(), timeout=remaining)
            except StopAsyncIteration:
                status = "success"
                return
            except TimeoutError as exc:
                raise LLMTimeoutError("Streamed answer exceeded CHAT_RESPONSE_DEADLINE_SECONDS") from exc
            produced.append(piece)
            yield piece
    finally:
        _record_llm(prompt, provider.name, "".join(produced), started, status if produced or status == "success" else "failed")
        await stream.aclose()


def active_model_name() -> str:
    return factory.get_llm_provider().model_name


def active_provider_name() -> str:
    return factory.get_llm_provider().name
