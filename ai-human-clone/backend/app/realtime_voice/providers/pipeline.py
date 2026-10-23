"""The "pipeline" provider: real-time voice from the platform's own services.

One turn = speech-to-text (the configured STT, with the usual voice checks and rate
limits) -> the clone's normal chat pipeline, streamed (logged-in users:
chat_service.prepare_stream, so the same prompt, knowledge, approved memories,
history, plan limits and saving as /chat/stream; visitors: the public pipeline with
public documents only) -> the answer spoken sentence by sentence by the clone's voice
(cloned or AI voice) while the text is still streaming.

No raw audio or transcripts are logged or kept by this module; the conversation
messages are saved exactly as in chat.
"""

import asyncio
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.concurrency import run_in_threadpool

from app.ai import factory as llm_factory
from app.ai import public_rag_pipeline, rag_pipeline
from app.ai.base import LLMError
from app.core.config import get_settings
from app.models import CloneProfile, User
from app.realtime_voice.db import open_db
from app.realtime_voice.exceptions import RealtimeVoiceError
from app.realtime_voice.provider_base import Emit, RealtimeProvider, TurnContext
from app.schemas.chat import ChatRequest
from app.services import chat_service, clone_service, monitoring, public_service, public_session_service, voice_service
from app.services.rate_limit import check_public_rate
from app.voice import factory as voice_factory
from app.voice import routing
from app.voice.audio import _FORMATS, sniff_format
from app.voice.base import VoiceError
from app.voice.text_to_speech import speakable, synthesize_audio

logger = logging.getLogger(__name__)

NAME = "pipeline"
# Answers are spoken per sentence; a very long sentence is cut at a space.
_SENTENCE_END = re.compile(r"(?<=[.!?۔؟।])\s+|\n+")
MAX_SENTENCE_CHARACTERS = 300


def take_sentences(buffer: str, final: bool) -> tuple[list[str], str]:
    """Complete sentences in `buffer` and the unfinished rest (everything when `final`)."""
    pieces = _SENTENCE_END.split(buffer)
    done, rest = (pieces, "") if final else (pieces[:-1], pieces[-1])
    while len(rest) > MAX_SENTENCE_CHARACTERS:
        cut = rest.rfind(" ", 0, MAX_SENTENCE_CHARACTERS)
        cut = cut if cut > 0 else MAX_SENTENCE_CHARACTERS
        done.append(rest[:cut])
        rest = rest[cut:].lstrip()
    return [piece.strip() for piece in done if piece and piece.strip()], rest


def upload_name(data: bytes) -> tuple[str, str]:
    """(filename, MIME type) matching the audio's real format, for the STT upload checks."""
    fmt = sniff_format(data)
    if fmt is None:
        raise RealtimeVoiceError("invalid_audio")
    extensions, mimes, _ = _FORMATS[fmt]
    return f"utterance.{sorted(extensions)[0]}", sorted(mimes)[0]


class _Speaker:
    """Speaks queued sentences one after another while the answer is still streaming."""

    def __init__(
        self,
        turn: int,
        emit: Emit,
        voice: str | None,
        language_of: Callable[[str], str | None],
        account_id: uuid.UUID | None,
        clone_id: uuid.UUID,
    ) -> None:
        self.turn = turn
        self.emit = emit
        self.voice = voice
        self.language_of = language_of
        self.account_id = account_id
        self.clone_id = clone_id
        self.buffer = ""
        self.seq = 0
        self.failed = False
        self.queue: asyncio.Queue[str | None] = asyncio.Queue()
        self.task = asyncio.create_task(self._run())

    def feed(self, piece: str) -> None:
        self.buffer += piece
        sentences, self.buffer = take_sentences(self.buffer, final=False)
        for sentence in sentences:
            self.queue.put_nowait(sentence)

    async def finish(self) -> None:
        sentences, self.buffer = take_sentences(self.buffer, final=True)
        for sentence in sentences:
            self.queue.put_nowait(sentence)
        self.queue.put_nowait(None)
        await self.task

    def cancel(self) -> None:
        self.task.cancel()

    async def _run(self) -> None:
        while True:
            sentence = await self.queue.get()
            if sentence is None:
                return
            spoken = speakable(sentence)
            if self.failed or not spoken:
                continue
            try:
                data, mime = await synthesize_audio(
                    spoken, self.voice, self.language_of(spoken), account_id=self.account_id, clone_id=self.clone_id
                )
            except VoiceError as exc:
                # The text answer still arrives; one notice, then no more speech this turn.
                logger.warning("Real-time speech failed (%s)", type(exc).__name__)
                self.failed = True
                await self.emit(
                    {"type": "error", "code": "provider_unavailable", "message": exc.user_message, "turn": self.turn, "fatal": False},
                    None,
                )
                continue
            await self.emit({"type": "audio", "turn": self.turn, "seq": self.seq, "mime": mime}, data)
            self.seq += 1


Piece = Callable[[str], Awaitable[None]]


class PipelineProvider(RealtimeProvider):
    name = NAME

    def configured(self) -> bool:
        try:
            llm_factory.get_llm_provider()
        except Exception:  # noqa: BLE001 - "not configured" in any form
            return False
        return bool(voice_factory.provider_status().get("stt"))

    def capabilities(self, clone: CloneProfile) -> dict:
        status = voice_factory.provider_status()
        cloned = routing.cloned_voice_active(clone)
        return {
            "transport": "websocket",
            "interruption": True,
            "streaming_text": True,
            "server_speech": bool(status.get("tts")) or cloned,
            "cloned_voice": cloned,
            # What the configured speech-to-text understands: English and Urdu speech; answers
            # in Roman Urdu are spoken too (see docs/voice-clone/local.md for quality limits).
            "languages": ["en", "ur", "roman-ur"] if status.get("stt") else [],
        }

    async def run_turn(self, ctx: TurnContext, turn: int, *, audio: bytes | None, text: str | None, emit: Emit) -> None:
        speaker: _Speaker | None = None
        parts: list[str] = []

        async def on_piece(piece: str) -> None:
            parts.append(piece)
            await emit({"type": "answer_delta", "turn": turn, "text": piece}, None)
            if speaker is not None:
                speaker.feed(piece)

        def start_speaker(voice: str | None, language_of: Callable[[str], str | None], account_id) -> None:
            nonlocal speaker
            if ctx.speech_mode == "voice":
                speaker = _Speaker(turn, emit, voice, language_of, account_id, ctx.clone_id)

        try:
            if ctx.is_public:
                message_id = await self._public_turn(ctx, turn, audio, text, emit, on_piece, start_speaker)
            else:
                message_id = await self._user_turn(ctx, turn, audio, text, emit, on_piece, start_speaker)
            await emit(
                {"type": "answer", "turn": turn, "text": "".join(parts), "message_id": str(message_id) if message_id else None},
                None,
            )
            if speaker is not None:
                await speaker.finish()
            await emit({"type": "turn_done", "turn": turn}, None)
        finally:
            if speaker is not None and not speaker.task.done():
                speaker.cancel()

    # --- logged-in users ----------------------------------------------------------------

    async def _user_turn(self, ctx, turn, audio, text, emit, on_piece: Piece, start_speaker) -> uuid.UUID:
        with open_db() as db:
            user = db.get(User, ctx.user_id)
            if user is None or not user.is_active:
                raise RealtimeVoiceError("forbidden")
            clone = clone_service.get_chat_clone(db, ctx.clone_id, user)  # access is re-checked every turn
            input_mode = "text"
            if audio is not None:
                filename, mime = upload_name(audio)
                heard = await voice_service.transcribe(clone, user, audio, filename, mime)
                text = heard.text
                input_mode = "voice"
                await emit({"type": "transcript", "turn": turn, "text": text, "language": heard.language}, None)
            stream_turn = await chat_service.prepare_stream(
                db, clone, user, ChatRequest(message=text, conversation_id=ctx.conversation_id, input_mode=input_mode)
            )
            voice = routing.effective_voice(clone)
            start_speaker(voice, lambda spoken: voice_service.speech_language(clone, spoken), user.id)
        ctx.conversation_id = stream_turn.conversation_id

        parts: list[str] = []
        started = time.monotonic()
        try:
            async for piece in rag_pipeline.stream_clone_response(stream_turn.prompt):
                parts.append(piece)
                await on_piece(piece)
        except asyncio.CancelledError:
            # Interrupted: keep what was already said, like a cut-off sentence in a call.
            if "".join(parts).strip():
                await asyncio.shield(chat_service.finish_streamed_turn(stream_turn, "".join(parts), started))
            raise
        answer = "".join(parts)
        if not answer.strip():
            raise LLMError("The model returned an empty answer")
        message = await chat_service.finish_streamed_turn(stream_turn, answer, started)
        return message.id

    # --- public visitors (public documents only, public limits) ---------------------------

    async def _public_turn(self, ctx, turn, audio, text, emit, on_piece: Piece, start_speaker) -> uuid.UUID:
        visitor = public_service.Visitor(address=ctx.visitor_address)
        with open_db() as db:
            clone = db.get(CloneProfile, ctx.clone_id)
            if clone is None:
                raise RealtimeVoiceError("session_not_found")
            from app.realtime_voice import permissions

            permissions.require_public(clone)
            session = public_service.session_for(db, clone, ctx.public_token)
            input_mode = "text"
            if audio is not None:
                filename, mime = upload_name(audio)
                heard = await public_service.transcribe(clone, visitor, audio, filename, mime)
                text = heard.text
                input_mode = "voice"
                await emit({"type": "transcript", "turn": turn, "text": text, "language": heard.language}, None)
            check_public_rate("chat", visitor.address)
            if public_session_service.messages_left(session) <= 0:
                raise RealtimeVoiceError("quota_exceeded", public_service.LIMIT_REACHED, 429)
            question = public_session_service.add_message(db, session, "user", text, input_mode)
            history = public_session_service.recent_history(
                db, session, get_settings().max_conversation_messages, exclude=question.id
            )
            context = await run_in_threadpool(public_rag_pipeline.retrieve_public_context, db, clone, text)
            prompt = public_rag_pipeline.prepare_public_prompt(clone, text, context, history)
            voice = routing.effective_voice(clone)
            start_speaker(voice, lambda spoken: voice_service.speech_language(clone, spoken), None)

        parts: list[str] = []
        started = time.monotonic()

        async def save() -> uuid.UUID:
            with open_db() as db:
                clone_row = db.get(CloneProfile, ctx.clone_id)
                session_row = public_session_service.require(db, clone_row, ctx.public_token)
                answer = public_session_service.add_message(db, session_row, "assistant", "".join(parts))
            monitoring.usage(
                "PUBLIC_CHAT_MESSAGE",
                provider=rag_pipeline.active_provider_name(),
                clone_id=ctx.clone_id,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            return answer.id

        try:
            async for piece in rag_pipeline.stream_clone_response(prompt):
                parts.append(piece)
                await on_piece(piece)
        except asyncio.CancelledError:
            if "".join(parts).strip():
                await asyncio.shield(save())
            raise
        if not "".join(parts).strip():
            raise LLMError("The model returned an empty answer")
        return await save()
