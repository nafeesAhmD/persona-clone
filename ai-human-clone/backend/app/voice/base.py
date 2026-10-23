"""Provider-independent voice interfaces.

SpeechToTextProvider turns audio into text; TextToSpeechProvider turns text
into audio. Routes and services only use these interfaces (via
app/voice/factory.py), so providers can be swapped with STT_PROVIDER /
TTS_PROVIDER without touching the rest of the app.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


class VoiceError(Exception):
    """Base error for voice failures the API layer handles.

    `str(exc)` holds technical detail for server logs; `user_message` is the
    safe text shown to users (no keys, hosts or raw provider errors).
    """

    status_code = 502
    user_message = "The voice service had a problem. Please try again."


class VoiceNotConfiguredError(VoiceError):
    status_code = 503
    user_message = "Voice is not available on this server right now."


class VoiceRateLimitError(VoiceError):
    status_code = 429
    user_message = "The AI voice is busy or has reached its free usage limit for now. Please try again later."


class VoiceTimeoutError(VoiceError):
    status_code = 504
    user_message = "The voice service took too long. Please try again."


class VoiceUnavailableError(VoiceError):
    status_code = 503
    user_message = "The voice service is temporarily unavailable. Please try again shortly."


class InvalidAudioError(VoiceError):
    """The upload isn't usable audio. The message is safe to show."""

    status_code = 400

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.user_message = message
        self.status_code = status_code


class NoSpeechError(VoiceError):
    status_code = 422
    user_message = "No speech was recognised in the recording. Please try again and speak clearly."


@dataclass(frozen=True)
class AudioClip:
    """Validated audio, normalised to 16 kHz mono 16-bit WAV (any provider accepts it)."""

    wav: bytes
    duration_seconds: float


@dataclass(frozen=True)
class Transcription:
    text: str
    language: str | None  # ISO 639-1 code (e.g. "en", "ur"), or None if unknown


@dataclass(frozen=True)
class SpeechAudio:
    """Audio a TTS provider produced, in any container PyAV can read."""

    data: bytes
    mime_type: str


@dataclass(frozen=True)
class VoiceOption:
    id: str
    name: str
    description: str
    # True for a personalised voice (e.g. cloned from the owner's recordings);
    # such voices always need the owner's voice consent.
    is_custom: bool = False


class SpeechToTextProvider(ABC):
    name: str

    @abstractmethod
    async def transcribe(self, audio: AudioClip, language_hint: str | None = None) -> Transcription:
        """Transcribe in the language spoken (never translate).

        `language_hint` is the clone's language, used to pick the script
        (e.g. Urdu script vs Roman Urdu); the speaker may use another language.
        """


class TextToSpeechProvider(ABC):
    name: str

    @abstractmethod
    def voices(self) -> list[VoiceOption]:
        """Voices this provider offers."""

    @property
    def default_voice(self) -> str:
        return self.voices()[0].id

    @abstractmethod
    async def synthesize(self, text: str, voice: str, language: str | None = None) -> SpeechAudio:
        """Speak `text` with `voice`. `language` (ISO code) is a hint for pronunciation."""
