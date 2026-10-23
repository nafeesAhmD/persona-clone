"""Which voice a clone speaks with, and which provider speaks it.

clone.voice_id always holds the clone's prebuilt voice (from the TTS provider in
app/voice/factory.py). When the owner made a personal voice clone and turned
`use_cloned_voice` on, the clone speaks with its cloned voice instead. Every caller
of generate_speech passes `effective_voice(clone)`, so voice chat, spoken replies,
the voice test, public voice, avatar videos and live calls all switch together, and
turning the cloned voice off falls back to the prebuilt voice without losing it.

Cloned voices are provider-prefixed, both in clone_profiles.voice_clone_id and in
the voice passed to generate_speech: "elevenlabs:<id>" (ElevenLabs) or "local:<hex>"
(the self-hosted Chatterbox service). Ids stored before the local provider existed
have no prefix and are ElevenLabs voices. The prefix decides where a voice is spoken
and deleted, even if VOICE_CLONE_PROVIDER has changed since it was made.
"""

from typing import Protocol

from app.core.config import get_settings
from app.voice.base import TextToSpeechProvider
from app.voice.providers import elevenlabs, local_clone

PROVIDERS = {elevenlabs.NAME: elevenlabs, local_clone.NAME: local_clone}
LEGACY_PROVIDER = elevenlabs.NAME
CLONED_PREFIX = f"{elevenlabs.NAME}:"  # kept for older imports
NOT_AVAILABLE = "Voice cloning isn't set up on this server (ELEVENLABS_API_KEY or the local voice-clone service)."


class _VoiceClone(Protocol):
    voice_id: str | None
    voice_consent_given: bool
    voice_clone_id: str | None
    voice_clone_status: str
    use_cloned_voice: bool


class VoiceCloneUnavailableError(elevenlabs.VoiceCloneNotConfiguredError):
    user_message = NOT_AVAILABLE


def active_provider() -> str | None:
    """The provider new voices are cloned with (VOICE_CLONE_PROVIDER), or None when cloning is off."""
    choice = (get_settings().voice_clone_provider or "auto").lower()
    if choice == "none":
        return None
    if choice in PROVIDERS:
        return choice if PROVIDERS[choice].configured() else None
    if elevenlabs.configured():
        return elevenlabs.NAME
    if local_clone.configured():
        return local_clone.NAME
    return None


def clone_provider(name: str | None = None) -> TextToSpeechProvider:
    """The client for `name` (default: the active provider). 503 when it isn't set up."""
    name = name or active_provider()
    if name is None:
        raise VoiceCloneUnavailableError("No voice clone provider is configured")
    return PROVIDERS[name].get_provider()


def provider_configured(name: str) -> bool:
    """The server can talk to `name` (credentials/URL set), whatever provider is active."""
    module = PROVIDERS.get(name)
    return bool(module and module.configured())


def split(voice_clone_id: str) -> tuple[str, str]:
    """(provider, provider's own voice id) of a stored or prefixed cloned voice id."""
    provider, sep, rest = voice_clone_id.partition(":")
    if sep and provider in PROVIDERS:
        return provider, rest
    return LEGACY_PROVIDER, voice_clone_id


def stored_id(provider: str, voice_id: str) -> str:
    """The value kept in clone_profiles.voice_clone_id."""
    return f"{provider}:{voice_id}"


def provider_of(voice_clone_id: str | None) -> str | None:
    return split(voice_clone_id)[0] if voice_clone_id else None


def cloned_voice_ref(voice_clone_id: str) -> str:
    """The voice id used for a cloned voice in settings and generate_speech ("<provider>:<id>")."""
    return stored_id(*split(voice_clone_id))


def is_cloned(voice: str | None) -> bool:
    return bool(voice) and any(voice.startswith(f"{name}:") for name in PROVIDERS)


def cloned_voice_id(voice: str) -> str:
    return split(voice)[1]


def cloned_voice_active(clone: _VoiceClone) -> bool:
    """The cloned voice is used: ready, switched on, consented and the server can speak it."""
    return bool(
        clone.use_cloned_voice
        and clone.voice_clone_status == "ready"
        and clone.voice_clone_id
        and clone.voice_consent_given
        and can_speak(clone.voice_clone_id)
    )


def can_speak(voice_clone_id: str) -> bool:
    """The provider that made this voice is reachable and cloning isn't switched off."""
    if (get_settings().voice_clone_provider or "auto").lower() == "none":
        return False
    return provider_configured(provider_of(voice_clone_id))


def effective_voice(clone: _VoiceClone) -> str | None:
    """The voice to pass to generate_speech for this clone."""
    if cloned_voice_active(clone):
        return cloned_voice_ref(clone.voice_clone_id)
    return clone.voice_id
