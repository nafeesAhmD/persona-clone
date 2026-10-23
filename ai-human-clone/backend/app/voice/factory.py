"""Chooses the speech-to-text and text-to-speech providers from settings.

STT_PROVIDER / TTS_PROVIDER: "auto" (Gemini when a key is available), a
provider name, or "none" to turn the feature off. To add a provider,
implement the interface in app/voice/base.py and register it below.
"""

import logging
from functools import lru_cache

from app.core.config import Settings, get_settings
from app.voice.base import SpeechToTextProvider, TextToSpeechProvider, VoiceNotConfiguredError
from app.voice.providers.gemini import GeminiSpeechToText, GeminiTextToSpeech

logger = logging.getLogger(__name__)

_STT: dict[str, type[SpeechToTextProvider]] = {"gemini": GeminiSpeechToText}
_TTS: dict[str, type[TextToSpeechProvider]] = {"gemini": GeminiTextToSpeech}


def _has_key(name: str, own_key: str | None, settings: Settings) -> bool:
    return name == "gemini" and bool(own_key or settings.gemini_api_key)


def _resolve(kind: str, requested: str, registry: dict, own_key: str | None, settings: Settings) -> str:
    requested = requested.strip().lower()
    if requested == "none":
        raise VoiceNotConfiguredError(f"{kind} is turned off ({kind.upper()}_PROVIDER=none)")
    if requested != "auto":
        if requested not in registry:
            raise VoiceNotConfiguredError(f"Unknown {kind} provider '{requested}'")
        return requested
    for name in registry:
        if _has_key(name, own_key, settings):
            return name
    raise VoiceNotConfiguredError(f"No {kind} provider has an API key")


@lru_cache
def get_stt_provider() -> SpeechToTextProvider:
    settings = get_settings()
    name = _resolve("stt", settings.stt_provider, _STT, settings.stt_api_key, settings)
    logger.info("Using speech-to-text provider: %s", name)
    return _STT[name](settings)


@lru_cache
def get_tts_provider() -> TextToSpeechProvider:
    settings = get_settings()
    name = _resolve("tts", settings.tts_provider, _TTS, settings.tts_api_key, settings)
    logger.info("Using text-to-speech provider: %s", name)
    return _TTS[name](settings)


def provider_status() -> dict[str, str | None]:
    """Which providers are active (None = not configured). Never raises."""
    status: dict[str, str | None] = {}
    for kind, getter in (("stt", get_stt_provider), ("tts", get_tts_provider)):
        try:
            status[kind] = getter().name
        except VoiceNotConfiguredError:
            status[kind] = None
    return status
