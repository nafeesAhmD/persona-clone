"""ElevenLabs: Instant Voice Cloning and text-to-speech with a cloned voice.

Only used for an owner's personal voice clone (app/services/voice_clone_service.py);
prebuilt voices still come from the TTS provider in app/voice/factory.py.
Cloned voices are addressed as "elevenlabs:<voice_id>" (see app/voice/routing.py).

The API key is sent only in the `xi-api-key` header and is never logged or
returned. Audio and text are never logged either: only sizes and status codes.
"""

import logging

import httpx

from app.core.config import get_settings
from app.voice.base import (
    InvalidAudioError,
    SpeechAudio,
    TextToSpeechProvider,
    VoiceError,
    VoiceNotConfiguredError,
    VoiceOption,
    VoiceRateLimitError,
    VoiceTimeoutError,
    VoiceUnavailableError,
)

logger = logging.getLogger(__name__)

NAME = "elevenlabs"
CLONE_TIMEOUT_SECONDS = 120.0
DELETE_TIMEOUT_SECONDS = 20.0
OUTPUT_FORMAT = "mp3_44100_128"
VOICE_SETTINGS = {"stability": 0.5, "similarity_boost": 0.8, "style": 0.15}

NOT_CONFIGURED = "Voice cloning isn't set up on this server (ELEVENLABS_API_KEY)."
INVALID_SAMPLES = (
    "The voice service couldn't use these recordings. Record again in a quiet room, "
    "speaking naturally (one speaker only)."
)

_transport: httpx.BaseTransport | httpx.AsyncBaseTransport | None = None  # tests set httpx.MockTransport


class VoiceCloneNotConfiguredError(VoiceNotConfiguredError):
    user_message = NOT_CONFIGURED


class VoiceCloneQuotaError(VoiceUnavailableError):
    user_message = "Your cloned voice can't be used right now: the voice service's usage limit was reached."


class VoiceNotFoundError(VoiceError):
    """The cloned voice no longer exists at ElevenLabs."""

    status_code = 409
    user_message = "Your cloned voice no longer exists at the voice service. Please create it again."


def configured() -> bool:
    return bool(get_settings().elevenlabs_api_key)


def _require_key() -> str:
    key = get_settings().elevenlabs_api_key
    if not key:
        raise VoiceCloneNotConfiguredError("ELEVENLABS_API_KEY is not set")
    return key


def _common(timeout: float) -> dict:
    settings = get_settings()
    return {
        "base_url": settings.elevenlabs_api_url.rstrip("/"),
        "headers": {"xi-api-key": _require_key()},
        "timeout": httpx.Timeout(timeout, connect=min(10.0, timeout)),
        "transport": _transport,
    }


def _check(response: httpx.Response, what: str) -> None:
    """Map an ElevenLabs error status to a VoiceError with a safe user message."""
    code = response.status_code
    if code < 400:
        return
    detail = f"ElevenLabs {what} returned {code}"  # never the body: it can echo request data
    if code == 401:
        raise VoiceCloneNotConfiguredError(f"{detail} (API key rejected)")
    if code == 402:
        raise VoiceCloneQuotaError(f"{detail} (quota or plan)")
    if code == 429:
        raise VoiceRateLimitError(detail)
    if code == 404:
        raise VoiceNotFoundError(detail)
    if code in (400, 422):
        raise InvalidAudioError(INVALID_SAMPLES) if what == "voice clone" else VoiceError(detail)
    if code == 403:
        raise VoiceCloneQuotaError(f"{detail} (not allowed on this plan)")
    raise VoiceUnavailableError(detail)


class ElevenLabsVoice(TextToSpeechProvider):
    """Clone, speak with and delete personal voices at ElevenLabs."""

    name = NAME

    def voices(self) -> list[VoiceOption]:
        return []  # cloned voices belong to one clone each; see voice_clone_service

    async def clone_voice(
        self, name: str, files: list[tuple[str, bytes, str]], remove_background_noise: bool = False
    ) -> str:
        """Create an Instant Voice Clone from `files` [(filename, bytes, mime)]; returns its voice id."""
        form = {"name": name[:100], "remove_background_noise": "true" if remove_background_noise else "false",
                "description": "Personal voice for a Clone Me clone (owner consented)."}
        upload = [("files", (filename, data, mime)) for filename, data, mime in files]
        try:
            async with httpx.AsyncClient(**_common(CLONE_TIMEOUT_SECONDS)) as client:
                response = await client.post("/v1/voices/add", data=form, files=upload)
        except httpx.TimeoutException as exc:
            raise VoiceTimeoutError("ElevenLabs voice clone timed out") from exc
        except httpx.HTTPError as exc:
            raise VoiceUnavailableError(f"ElevenLabs voice clone failed ({type(exc).__name__})") from exc
        _check(response, "voice clone")
        try:
            voice_id = response.json().get("voice_id")
        except ValueError:
            voice_id = None
        if not voice_id:
            raise VoiceUnavailableError("ElevenLabs voice clone returned no voice_id")
        logger.info("Created an ElevenLabs voice clone from %d file(s)", len(files))
        return str(voice_id)

    async def synthesize(self, text: str, voice: str, language: str | None = None) -> SpeechAudio:
        settings = get_settings()
        body: dict = {"text": text, "model_id": settings.elevenlabs_model, "voice_settings": VOICE_SETTINGS}
        if language:
            body["language_code"] = language.split("-")[0].lower()
        try:
            async with httpx.AsyncClient(**_common(settings.voice_timeout_seconds)) as client:
                response = await client.post(
                    f"/v1/text-to-speech/{voice}",
                    params={"output_format": OUTPUT_FORMAT},
                    json=body,
                    headers={"Accept": "audio/mpeg"},
                )
        except httpx.TimeoutException as exc:
            raise VoiceTimeoutError("ElevenLabs speech timed out") from exc
        except httpx.HTTPError as exc:
            raise VoiceUnavailableError(f"ElevenLabs speech failed ({type(exc).__name__})") from exc
        _check(response, "speech")
        if not response.content:
            raise VoiceUnavailableError("ElevenLabs returned no audio")
        return SpeechAudio(data=response.content, mime_type="audio/mpeg")

    def delete_voice(self, voice_id: str) -> None:
        """Delete a cloned voice. A voice that is already gone (404) counts as deleted."""
        try:
            with httpx.Client(**_common(DELETE_TIMEOUT_SECONDS)) as client:
                response = client.delete(f"/v1/voices/{voice_id}")
        except httpx.TimeoutException as exc:
            raise VoiceTimeoutError("ElevenLabs voice delete timed out") from exc
        except httpx.HTTPError as exc:
            raise VoiceUnavailableError(f"ElevenLabs voice delete failed ({type(exc).__name__})") from exc
        if response.status_code == 404:
            return
        _check(response, "voice delete")
        logger.info("Deleted an ElevenLabs voice clone")


def get_provider() -> ElevenLabsVoice:
    """The ElevenLabs client. Raises VoiceCloneNotConfiguredError (503) without a key."""
    _require_key()
    return ElevenLabsVoice()
