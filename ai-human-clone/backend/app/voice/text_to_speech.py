"""Text-to-speech: answer text -> speakable text -> provider -> MP3 in voice storage."""

import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass

from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.services import monitoring
from app.voice import factory, routing
from app.voice.audio import encode_mp3
from app.voice.base import SpeechAudio, TextToSpeechProvider, VoiceError, VoiceTimeoutError
from app.voice.providers import local_clone
from app.voice.storage import MIME_TYPES, get_voice_store

logger = logging.getLogger(__name__)

_CODE_BLOCK = re.compile(r"```.*?```", re.DOTALL)
_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MARKUP = re.compile(r"(\*\*|__|`|~~|^#{1,6}\s*|^\s*[-*•]\s+|^\s*>\s?)", re.MULTILINE)
_SENTENCE_END = re.compile(r"[.!?۔؟](\s|$)")


@dataclass(frozen=True)
class GeneratedSpeech:
    audio_id: str
    mime_type: str


def speakable(text: str, max_characters: int | None = None) -> str:
    """Plain text for reading aloud: no Markdown or code, cut at a sentence end if too long."""
    limit = max_characters or get_settings().tts_max_characters
    text = _CODE_BLOCK.sub(" ", text)
    text = _LINK.sub(r"\1", text)
    text = _MARKUP.sub("", text)
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    ends = [m.end() for m in _SENTENCE_END.finditer(cut)]
    return cut[: ends[-1]].strip() if ends else cut.rsplit(" ", 1)[0]


def _provider_for(voice: str | None) -> tuple[TextToSpeechProvider, str]:
    """A cloned voice ("elevenlabs:<id>" or "local:<id>", see app/voice/routing.py) is spoken
    by the provider that made it; any other voice by the configured TTS provider."""
    if routing.is_cloned(voice):
        name, voice_id = routing.split(voice)
        return routing.clone_provider(name), voice_id
    provider = factory.get_tts_provider()
    return provider, voice or provider.default_voice


def _timeout_for(provider: TextToSpeechProvider) -> float:
    """The local voice-clone service runs on CPU and is much slower than hosted TTS."""
    settings = get_settings()
    if provider.name == local_clone.NAME:
        return settings.local_voice_clone_timeout_seconds
    return settings.voice_timeout_seconds


def _to_mp3(audio: SpeechAudio) -> tuple[bytes, str]:
    if audio.mime_type == "audio/mpeg":  # already MP3 (e.g. ElevenLabs): don't re-encode
        return audio.data, audio.mime_type
    try:
        return encode_mp3(audio.data), "audio/mpeg"
    except Exception as exc:  # noqa: BLE001 - fall back to the provider's own (browser-playable) WAV
        logger.warning("MP3 encoding failed, keeping WAV: %s", type(exc).__name__)
        return audio.data, audio.mime_type


_CACHE_NAMESPACE = uuid.UUID("0d7f2c55-6a1e-4f3b-9d8a-2b6c1e4f7a90")


async def generate_speech(
    text: str,
    voice: str | None,
    language: str | None,
    *,
    user_id: uuid.UUID,
    cache_key: str | None = None,
    account_id: uuid.UUID | None = None,
    clone_id: uuid.UUID | None = None,
) -> GeneratedSpeech:
    """Speak `text` and store the audio for `user_id`. Raises VoiceError on failure.

    With `cache_key` (e.g. a message id), an unexpired recording of the same text,
    voice and language is reused instead of asking the provider again, which
    matters on free tiers that allow only a few requests a day.
    `user_id` owns the stored file (a user, or a visitor session); `account_id` and
    `clone_id` are only for usage records (character counts, never the text).
    """
    spoken = speakable(text)
    if not spoken:
        raise VoiceError("Nothing to speak")
    provider, voice_id = _provider_for(voice)
    store = get_voice_store()
    audio_id = None
    started = time.monotonic()

    def record(status: str) -> None:
        monitoring.usage(
            "TTS_REQUEST",
            provider=provider.name,
            status=status,
            user_id=account_id,
            clone_id=clone_id,
            input_units=len(spoken),
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    if cache_key:
        audio_id = uuid.uuid5(_CACHE_NAMESPACE, f"{cache_key}:{provider.name}:{voice_id}:{language}").hex
        cached = await run_in_threadpool(store.find, user_id, audio_id)
        if cached is not None:
            record("cached")
            return GeneratedSpeech(audio_id=audio_id, mime_type=MIME_TYPES[cached.suffix.lstrip(".")])
    timeout = _timeout_for(provider)
    try:
        audio = await asyncio.wait_for(provider.synthesize(spoken, voice_id, language), timeout=timeout)
    except TimeoutError as exc:
        record("failed")
        raise VoiceTimeoutError(f"Speech generation exceeded {timeout:g} seconds") from exc
    except Exception:
        record("failed")
        raise
    record("success")
    data, mime = await run_in_threadpool(_to_mp3, audio)
    audio_id = await run_in_threadpool(store.save, user_id, data, mime, audio_id)
    logger.info("Generated %d characters of speech with %s (%s, %d bytes)", len(spoken), provider.name, voice_id, len(data))
    return GeneratedSpeech(audio_id=audio_id, mime_type=mime)


async def synthesize_audio(
    text: str,
    voice: str | None,
    language: str | None,
    *,
    account_id: uuid.UUID | None = None,
    clone_id: uuid.UUID | None = None,
) -> tuple[bytes, str]:
    """Speak `text` and return (audio bytes, MIME type) without storing a file.

    For streamed speech (Phase 17 real-time voice): the audio goes straight to the
    browser and is never kept. Same provider routing, timeouts and usage records as
    generate_speech. Raises VoiceError on failure.
    """
    spoken = speakable(text)
    if not spoken:
        raise VoiceError("Nothing to speak")
    provider, voice_id = _provider_for(voice)
    started = time.monotonic()
    timeout = _timeout_for(provider)
    status = "failed"
    try:
        audio = await asyncio.wait_for(provider.synthesize(spoken, voice_id, language), timeout=timeout)
        status = "success"
    except TimeoutError as exc:
        raise VoiceTimeoutError(f"Speech generation exceeded {timeout:g} seconds") from exc
    finally:
        monitoring.usage(
            "TTS_REQUEST",
            provider=provider.name,
            status=status,
            user_id=account_id,
            clone_id=clone_id,
            input_units=len(spoken),
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    return await run_in_threadpool(_to_mp3, audio)
