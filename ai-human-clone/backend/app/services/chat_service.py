"""Clone chat: conversation bookkeeping around the RAG pipeline.

Per turn:
1. rate-limit check, find/create the user's conversation, save the user message;
2. load recent history (MAX_CONVERSATION_MESSAGES, excluding this message);
3. retrieve the clone's knowledge and, in the owner's own chats, its approved
   long-term memories (rag_pipeline), then ask the LLM;
4. save the assistant reply only if generation succeeded, never a fake one.

Callers must already have checked chat access to the clone
(clone_service.get_chat_clone) with the authenticated user.
"""

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.ai import public_rag_pipeline, rag_pipeline
from app.ai.base import ChatTurn, LLMError
from app.ai.embedding_service import EmbeddingError
from app.ai.memory_search import RetrievedMemory
from app.ai.rag_context import RagContext
from app.ai.rag_pipeline import PreparedPrompt
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import CloneProfile, Conversation, Message, User
from app.schemas.chat import ChatRequest, ChatResponse, ChatSource, MessageRead
from app.services import conversation_service, memory_service, monitoring
from app.services.qdrant_service import VectorStoreError
from app.services.rate_limit import check_chat_rate

logger = logging.getLogger(__name__)

MEMORY_UNAVAILABLE = "The clone's memory is temporarily unavailable. Please try again shortly."


@dataclass
class _Turn:
    conversation: Conversation
    user_message: Message
    history: list[ChatTurn]
    owner_name: str | None


def _emit(event_type: str, clone_id, owner_id, organization_id, data: dict) -> None:
    """Webhook event for the clone's owner (and organization). Ids, counts and statuses
    only - never the message text. Never raises."""
    try:
        from app.developer.webhooks import emit_for_clone

        emit_for_clone(event_type, {"clone_id": clone_id, **data}, owner_id=owner_id, organization_id=organization_id)
    except Exception as exc:  # noqa: BLE001 - webhooks must never break a chat
        logger.warning("Could not emit %s: %s", event_type, type(exc).__name__)


def _start_turn(db: Session, clone: CloneProfile, user: User, request: ChatRequest, source: str = "app") -> _Turn:
    check_chat_rate(user.id)
    if source == "app":
        # The plan's monthly chat messages (Phase 12). Developer API calls check this
        # against the API key owner's plan before they get here.
        from app.developer import limits

        limits.check_chat_messages(db, acting_user_id=user.id, user_id=user.id, organization_id=None)
    conversation = conversation_service.get_or_create(db, clone, user, request.conversation_id, source=source)
    user_message = conversation_service.add_message(
        db, conversation, "user", request.message, input_mode=request.input_mode
    )
    if request.conversation_id is None:
        _emit(
            "conversation.created",
            clone.id,
            clone.owner_id,
            clone.organization_id,
            {
                "conversation_id": conversation.id,
                "input_mode": request.input_mode,
                "started_by": "owner" if _is_owner(clone, user) else "user",
            },
        )
    history = conversation_service.recent_history(
        db, conversation, get_settings().max_conversation_messages, exclude=user_message.id
    )
    owner_name = clone.owner.full_name if clone.owner else None
    return _Turn(conversation, user_message, history, owner_name)


def _is_owner(clone: CloneProfile, user: User) -> bool:
    return clone.owner_id == user.id


def _retrieve(db: Session, clone: CloneProfile, user: User, question: str) -> RagContext:
    """The owner: all knowledge and approved memories. Anyone else is a visitor and
    gets only content marked public (public_rag_pipeline), like anonymous visitors.
    """
    if not _is_owner(clone, user):
        return public_rag_pipeline.retrieve_public_context(db, clone, question)

    def confirmed(found: list[RetrievedMemory]) -> list[RetrievedMemory]:
        try:
            return memory_service.confirm_for_chat(db, clone, found)
        except Exception:
            db.rollback()
            raise

    context = rag_pipeline.retrieve_context(clone, question, include_memory=True, memory_filter=confirmed)
    if context.memories:
        try:
            memory_service.mark_used(db, [memory.memory_id for memory in context.memories])
        except Exception as exc:  # noqa: BLE001 - bookkeeping only
            db.rollback()
            logger.warning("Could not record memory use: %s", exc)
    return context


def _prompt(clone: CloneProfile, user: User, message: str, context: RagContext, turn: _Turn) -> PreparedPrompt:
    """The owner's prompt for the owner; the stricter public prompt for visitors."""
    if _is_owner(clone, user):
        prompt = rag_pipeline.prepare_prompt(clone, message, context, turn.history, turn.owner_name)
    else:
        prompt = public_rag_pipeline.prepare_public_prompt(clone, message, context, turn.history)
    prompt.user_id = user.id
    return prompt


def sources_of(context: RagContext) -> list[ChatSource]:
    """One entry per document (its best chunk score); titles only, no document text."""
    best: dict[str, ChatSource] = {}
    for hit in context.hits:
        if hit.document_id not in best or hit.score > best[hit.document_id].score:
            best[hit.document_id] = ChatSource(document_id=hit.document_id, title=hit.title, score=round(hit.score, 3))
    return sorted(best.values(), key=lambda s: s.score, reverse=True)


def _save_reply(
    db: Session, conversation: Conversation, text: str, context: RagContext, model: str, latency_ms: int | None
) -> Message:
    return conversation_service.add_message(
        db,
        conversation,
        "assistant",
        text,
        retrieved_chunks_count=len(context.hits),
        model_name=model[:100],
        latency_ms=latency_ms,
    )


async def chat(
    db: Session, clone: CloneProfile, user: User, request: ChatRequest, *, source: str = "app"
) -> ChatResponse:
    """Non-streaming turn. LLM/memory errors propagate (their handlers return safe messages).
    `source` marks new conversations as started in the app or through the developer API."""
    turn = await run_in_threadpool(_start_turn, db, clone, user, request, source)
    context = await run_in_threadpool(_retrieve, db, clone, user, request.message)
    reply = await rag_pipeline.answer(clone, _prompt(clone, user, request.message, context, turn))
    if not reply.text.strip():
        raise LLMError("The model returned an empty answer")
    message = await run_in_threadpool(
        _save_reply, db, turn.conversation, reply.text, context, reply.model_name, reply.latency_ms
    )
    await run_in_threadpool(
        _emit,
        "message.completed",
        clone.id,
        clone.owner_id,
        clone.organization_id,
        _message_data(message, turn.conversation.id, request.input_mode, False, len(context.hits), len(context.memories)),
    )
    monitoring.usage(
        "CHAT_MESSAGE", provider=reply.provider, user_id=user.id, clone_id=clone.id, duration_ms=reply.latency_ms
    )
    return ChatResponse(
        conversation_id=turn.conversation.id,
        message=MessageRead.model_validate(message),
        sources=sources_of(context),
        memories_used=len(context.memories),
    )


def _message_data(
    message: Message, conversation_id: uuid.UUID, input_mode: str | None, streamed: bool, sources: int, memories: int
) -> dict:
    return {
        "conversation_id": conversation_id,
        "message_id": message.id,
        "role": "assistant",
        "input_mode": input_mode or "text",
        "streamed": streamed,
        "model": message.model_name,
        "latency_ms": message.latency_ms,
        "sources_count": sources,
        "memories_used": memories,
    }


# --- Streaming ----------------------------------------------------------------


@dataclass
class StreamTurn:
    conversation_id: uuid.UUID
    prompt: PreparedPrompt
    # For webhook events (message.completed) once the streamed answer is saved.
    clone_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None
    organization_id: uuid.UUID | None = None
    input_mode: str | None = None


async def prepare_stream(db: Session, clone: CloneProfile, user: User, request: ChatRequest) -> StreamTurn:
    """Everything that can fail with a normal HTTP error, done before streaming starts."""
    turn = await run_in_threadpool(_start_turn, db, clone, user, request)
    context = await run_in_threadpool(_retrieve, db, clone, user, request.message)
    prompt = _prompt(clone, user, request.message, context, turn)
    return StreamTurn(
        conversation_id=turn.conversation.id,
        prompt=prompt,
        clone_id=clone.id,
        owner_id=clone.owner_id,
        organization_id=clone.organization_id,
        input_mode=request.input_mode,
    )


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _save_streamed_reply(
    conversation_id: uuid.UUID, text: str, context: RagContext, model: str, latency_ms: int
) -> Message:
    # The request's session may be closed once the response is streaming.
    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        return _save_reply(db, conversation, text, context, model, latency_ms)


async def finish_streamed_turn(turn: StreamTurn, text: str, started: float) -> Message:
    """Save a streamed answer, then the webhook event and the usage record. Shared by
    /chat/stream and real-time voice (app/realtime_voice), so both behave the same."""
    context = turn.prompt.context
    latency_ms = int((time.monotonic() - started) * 1000)
    model = rag_pipeline.active_model_name()
    message = await run_in_threadpool(_save_streamed_reply, turn.conversation_id, text, context, model, latency_ms)
    if turn.owner_id is not None:
        await run_in_threadpool(
            _emit,
            "message.completed",
            turn.clone_id,
            turn.owner_id,
            turn.organization_id,
            _message_data(message, turn.conversation_id, turn.input_mode, True, len(context.hits), len(context.memories)),
        )
    logger.info("Streamed answer for conversation %s by %s in %d ms", turn.conversation_id, model, latency_ms)
    monitoring.usage(
        "CHAT_MESSAGE",
        provider=rag_pipeline.active_provider_name(),
        user_id=turn.prompt.user_id,
        clone_id=turn.prompt.clone_id,
        duration_ms=latency_ms,
    )
    return message


async def stream_chat(turn: StreamTurn) -> AsyncIterator[str]:
    """Server-sent events: meta, then delta pieces, then done (or error with a safe message)."""
    context = turn.prompt.context
    yield _sse(
        "meta",
        {
            "conversation_id": str(turn.conversation_id),
            "sources": [source.model_dump() for source in sources_of(context)],
            "memories_used": len(context.memories),
        },
    )
    parts: list[str] = []
    started = time.monotonic()
    try:
        async for piece in rag_pipeline.stream_clone_response(turn.prompt):
            parts.append(piece)
            yield _sse("delta", {"text": piece})
        text = "".join(parts)
        if not text.strip():
            raise LLMError("The model returned an empty answer")
        message = await finish_streamed_turn(turn, text, started)
    except LLMError as exc:
        logger.warning("Chat generation failed (%s): %s", type(exc).__name__, exc)
        monitoring.error(exc, request=None, status_code=exc.status_code, category="llm", message=exc.user_message)
        yield _sse("error", {"detail": exc.user_message})
        return
    except (VectorStoreError, EmbeddingError) as exc:
        logger.warning("Chat memory failure: %s", exc)
        monitoring.error(exc, request=None, status_code=503, category="vector_store", message=MEMORY_UNAVAILABLE)
        yield _sse("error", {"detail": MEMORY_UNAVAILABLE})
        return
    except Exception as exc:
        logger.exception("Streaming chat failed")
        monitoring.error(exc, request=None, status_code=500, category="internal", message="Streaming chat failed")
        yield _sse("error", {"detail": "Something went wrong. Please try again."})
        return
    yield _sse("done", {"message": MessageRead.model_validate(message).model_dump(mode="json")})
