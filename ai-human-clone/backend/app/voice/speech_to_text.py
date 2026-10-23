"""Speech-to-text: validated upload -> provider -> transcript in the language spoken."""

import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass

from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.services import monitoring
from app.voice import factory
from app.voice.audio import validate_and_normalise
from app.voice.base import NoSpeechError, VoiceTimeoutError

logger = logging.getLogger(__name__)

_ARABIC_SCRIPT = re.compile(r"[؀-ۿ]")


@dataclass(frozen=True)
class TranscribedSpeech:
    text: str
    language: str | None
    duration_seconds: float


async def transcribe_audio(
    data: bytes,
    filename: str | None,
    content_type: str | None,
    *,
    language_hint: str | None = None,
    account_id: uuid.UUID | None = None,
    clone_id: uuid.UUID | None = None,
) -> TranscribedSpeech:
    """Raises InvalidAudioError (bad upload), NoSpeechError or another VoiceError.
    `account_id`/`clone_id` are for usage records only (seconds of audio, no content)."""
    clip = await run_in_threadpool(validate_and_normalise, data, filename, content_type)
    provider = factory.get_stt_provider()
    settings = get_settings()
    started = time.monotonic()

    def record(status: str) -> None:
        monitoring.usage(
            "STT_REQUEST",
            provider=provider.name,
            status=status,
            user_id=account_id,
            clone_id=clone_id,
            input_units=round(clip.duration_seconds, 2),
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    try:
        result = await asyncio.wait_for(
            provider.transcribe(clip, language_hint), timeout=settings.voice_timeout_seconds
        )
    except TimeoutError as exc:
        record("failed")
        raise VoiceTimeoutError("Transcription exceeded VOICE_TIMEOUT_SECONDS") from exc
    except Exception:
        record("failed")
        raise
    record("success")

    text = " ".join(result.text.split())[: settings.max_chat_message_length]
    if not text:
        raise NoSpeechError("The provider found no speech")
    language = result.language
    if _ARABIC_SCRIPT.search(text) and language in (None, "hi"):
        language = "ur"  # Hindustani speech written in Urdu script
    # Sizes and timings only; transcripts and audio are never logged.
    logger.info(
        "Transcribed %.1fs of audio with %s: %d characters, language=%s",
        clip.duration_seconds,
        provider.name,
        len(text),
        language,
    )
    return TranscribedSpeech(text=text, language=language, duration_seconds=clip.duration_seconds)
