"""Voice settings, consent, and voice chat on top of the existing text chat.

Voice chat = speech-to-text -> chat_service.chat (the same RAG + long-term
memory + LLM pipeline, conversation and saving as text chat) -> text-to-speech.
If speech generation fails after the answer was produced, the text answer is
still returned, with `tts_error`.

Rules:
- Voice can only be turned on after the owner gives voice consent; withdrawing
  consent turns voice off. (Also enforced by a database check constraint.)
- Voices are AI-generated. The owner's cloned voice (voice_clone_service) needs
  voice consent plus its own clone consent; withdrawing voice consent deletes it.
- Transcribe / voice chat need chat access to the clone AND voice turned on.
  Settings and the voice test are owner only (callers use get_managed_clone).
"""

import logging
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.models import CloneProfile, Message, User
from app.schemas.chat import ChatRequest
from app.schemas.voice import (
    VoiceChatResponse,
    VoiceOptionRead,
    VoiceSettingsRead,
    VoiceSettingsUpdate,
)
from app.services import chat_service, clone_service, conversation_service, voice_clone_service
from app.services.errors import ForbiddenError, InvalidInputError, NotFoundError
from app.services.rate_limit import check_voice_rate
from app.voice import factory, routing
from app.voice.base import TextToSpeechProvider, VoiceError, VoiceNotConfiguredError, VoiceOption
from app.voice.routing import effective_voice
from app.voice.speech_to_text import TranscribedSpeech, transcribe_audio
from app.voice.text_to_speech import generate_speech

logger = logging.getLogger(__name__)

VOICE_OFF = "Voice is turned off for this AI Clone."
PUBLIC_VOICE_OFF = "Voice isn't available to visitors of this AI Clone."
CONSENT_REQUIRED = "Voice consent is required before voice can be turned on."
CUSTOM_CONSENT_REQUIRED = "A personalised voice needs voice consent first."
TTS_UNAVAILABLE = "Voice generation temporarily unavailable"
CLONED_VOICE_NAME = "My voice (cloned)"
_ARABIC_SCRIPT = re.compile(r"[؀-ۿ]")


def audio_url(audio_id: str) -> str:
    return f"/api/voice/audio/{audio_id}"


def _tts_or_none() -> TextToSpeechProvider | None:
    try:
        return factory.get_tts_provider()
    except VoiceNotConfiguredError:
        return None


# --- Settings -------------------------------------------------------------------


def _cloned_option(clone: CloneProfile) -> VoiceOption | None:
    """The owner's cloned voice as a selectable option (when it's ready and usable here)."""
    if clone.voice_clone_status != "ready" or not clone.voice_clone_id or not routing.can_speak(clone.voice_clone_id):
        return None
    where = "ElevenLabs" if routing.provider_of(clone.voice_clone_id) == "elevenlabs" else "on this server"
    return VoiceOption(
        routing.cloned_voice_ref(clone.voice_clone_id),
        CLONED_VOICE_NAME,
        f"Your own voice, cloned from your recordings ({where}). Replies are still labelled AI-generated.",
        is_custom=True,
    )


def settings_of(clone: CloneProfile) -> VoiceSettingsRead:
    status = factory.provider_status()
    tts = _tts_or_none()
    voices = tts.voices() if tts else []
    cloned = _cloned_option(clone)
    if cloned is not None:
        voices = [cloned, *voices]
    cloned_in_use = routing.cloned_voice_active(clone)
    voice_id = routing.effective_voice(clone)
    selected = next((v for v in voices if v.id == voice_id), None)
    return VoiceSettingsRead(
        voice_enabled=clone.voice_enabled,
        voice_provider=routing.provider_of(clone.voice_clone_id) if cloned_in_use else clone.voice_provider,
        voice_id=voice_id,
        voice_language=clone.voice_language or "auto",
        voice_consent_given=clone.voice_consent_given,
        voice_consent_at=clone.voice_consent_at,
        voice_type="custom" if cloned_in_use or (selected and selected.is_custom) else "ai_generated",
        stt_provider=status["stt"],
        tts_provider=status["tts"],
        voices=[VoiceOptionRead(**v.__dict__) for v in voices],
        voice_clone=voice_clone_service.status_of(clone),
    )


def update_settings(db: Session, clone: CloneProfile, data: VoiceSettingsUpdate) -> CloneProfile:
    changes = data.model_dump(exclude_unset=True)
    withdrawn_voice = None

    if changes.get("voice_consent_given") is True and not clone.voice_consent_given:
        clone.voice_consent_given = True
        clone.voice_consent_at = datetime.now(UTC)
    elif changes.get("voice_consent_given") is False:
        clone.voice_consent_given = False
        clone.voice_consent_at = None
        clone.voice_enabled = False  # no voice without consent
        # Withdrawing consent also deletes the cloned voice (at the provider after the commit).
        withdrawn_voice = voice_clone_service.detach(clone)

    if changes.get("voice_language") is not None:
        clone.voice_language = None if changes["voice_language"] == "auto" else changes["voice_language"]

    # Choosing the cloned voice ("elevenlabs:<id>" / "local:<id>") in the voice list turns use_cloned_voice on;
    # choosing a prebuilt voice turns it off (the prebuilt voice is kept in clone.voice_id).
    selection = changes.get("voice_id")
    if routing.is_cloned(selection):
        if not clone.voice_consent_given:
            raise ForbiddenError(CUSTOM_CONSENT_REQUIRED)
        if _cloned_option(clone) is None or selection != routing.cloned_voice_ref(clone.voice_clone_id):
            raise InvalidInputError("Unknown voice for this provider")
        clone.use_cloned_voice = True
        prebuilt = {**changes, "voice_id": None}  # nothing to look up at the TTS provider
        if prebuilt.get("voice_provider") in routing.PROVIDERS:
            prebuilt["voice_provider"] = None
    else:
        prebuilt = changes
        if selection:
            clone.use_cloned_voice = False

    needs_provider = any(prebuilt.get(key) for key in ("voice_provider", "voice_id")) or changes.get("voice_enabled")
    tts = _tts_or_none() if needs_provider else None
    if needs_provider and tts is None:
        raise VoiceNotConfiguredError("No text-to-speech provider is configured")
    if prebuilt.get("voice_provider") and prebuilt["voice_provider"] != tts.name:
        raise InvalidInputError(f"Unknown voice provider. Available: {tts.name}")
    if prebuilt.get("voice_id"):
        option = next((v for v in tts.voices() if v.id == prebuilt["voice_id"]), None)
        if option is None:
            raise InvalidInputError("Unknown voice for this provider")
        if option.is_custom and not clone.voice_consent_given:
            raise ForbiddenError(CUSTOM_CONSENT_REQUIRED)
        clone.voice_id = option.id
        clone.voice_provider = tts.name

    if changes.get("voice_enabled") is True:
        if not clone.voice_consent_given:
            raise ForbiddenError(CONSENT_REQUIRED)
        factory.get_stt_provider()  # VoiceNotConfiguredError (503) if voice input can't work
        clone.voice_provider = clone.voice_provider or tts.name
        clone.voice_id = clone.voice_id or tts.default_voice
        clone.voice_enabled = True
    elif changes.get("voice_enabled") is False:
        clone.voice_enabled = False

    db.commit()
    db.refresh(clone)
    if withdrawn_voice:
        voice_clone_service.delete_at_provider(withdrawn_voice, clone.id)
    if changes:
        from app.services.clone_service import _emit

        _emit("clone.updated", clone, changed_fields=sorted(changes))
    return clone


def require_voice(clone: CloneProfile, *, visitor: bool = False) -> None:
    """Voice on (with consent); for visitors also public voice turned on by the owner."""
    if not (clone.voice_enabled and clone.voice_consent_given):
        raise ForbiddenError(VOICE_OFF)
    if visitor and not clone.public_voice_enabled:
        raise ForbiddenError(PUBLIC_VOICE_OFF)


# --- Voice use ------------------------------------------------------------------


def _language_hint(clone: CloneProfile) -> str | None:
    return clone.preferred_language or clone.voice_language


def speech_language(clone: CloneProfile, text: str) -> str | None:
    if clone.voice_language:
        return clone.voice_language
    return "ur" if _ARABIC_SCRIPT.search(text) else None  # None: the provider detects it


async def transcribe(
    clone: CloneProfile, user: User, data: bytes, filename: str | None, content_type: str | None
) -> TranscribedSpeech:
    require_voice(clone, visitor=clone.owner_id != user.id)
    check_voice_rate(user.id)
    return await transcribe_audio(data, filename, content_type, language_hint=_language_hint(clone), account_id=user.id, clone_id=clone.id)


def _emit_voice_completed(clone: CloneProfile, reply, speech: TranscribedSpeech, audio_generated: bool) -> None:
    """Webhook event: ids, duration and status only (no transcript, no answer text)."""
    try:
        from app.developer.webhooks import emit_for_clone

        emit_for_clone(
            "voice.completed",
            {
                "clone_id": clone.id,
                "conversation_id": reply.conversation_id,
                "message_id": reply.message.id,
                "audio_generated": audio_generated,
                "duration_seconds": round(float(speech.duration_seconds or 0), 2),
                "language": speech.language,
            },
            owner_id=clone.owner_id,
            organization_id=clone.organization_id,
        )
    except Exception as exc:  # noqa: BLE001 - webhooks must never break voice chat
        logger.warning("Could not emit voice.completed: %s", type(exc).__name__)


async def voice_chat(
    db: Session,
    clone: CloneProfile,
    user: User,
    data: bytes,
    filename: str | None,
    content_type: str | None,
    conversation_id: uuid.UUID | None,
    *,
    source: str = "app",
) -> VoiceChatResponse:
    speech = await transcribe(clone, user, data, filename, content_type)
    # Exactly the text chat turn: knowledge + memory search, LLM, both messages saved.
    reply = await chat_service.chat(
        db,
        clone,
        user,
        ChatRequest(message=speech.text, conversation_id=conversation_id, input_mode="voice"),
        source=source,
    )

    url, tts_error = None, None
    try:
        speech_audio = await generate_speech(
            reply.message.content,
            effective_voice(clone),
            speech_language(clone, reply.message.content),
            user_id=user.id,
            cache_key=str(reply.message.id),
            account_id=user.id,
            clone_id=clone.id,
        )
        url = audio_url(speech_audio.audio_id)
    except VoiceError as exc:
        logger.warning("Speech generation failed (%s): %s", type(exc).__name__, exc)
        tts_error = TTS_UNAVAILABLE
    except Exception:  # noqa: BLE001 - the text answer must still reach the user
        logger.exception("Speech generation failed")
        tts_error = TTS_UNAVAILABLE

    await run_in_threadpool(_emit_voice_completed, clone, reply, speech, url is not None)
    return VoiceChatResponse(
        conversation_id=reply.conversation_id,
        transcript=speech.text,
        answer=reply.message.content,
        audio_url=url,
        tts_error=tts_error,
        language=speech.language,
        duration_seconds=speech.duration_seconds,
        message=reply.message,
        sources=reply.sources,
        memories_used=reply.memories_used,
    )


async def speak_message(db: Session, user: User, conversation_id: uuid.UUID, message_id: uuid.UUID) -> str:
    """Speech for a saved answer in the user's own conversation (the chat screen's voice replies)."""
    conversation = conversation_service.get_owned(db, conversation_id, user)
    message = db.get(Message, message_id)
    if message is None or message.conversation_id != conversation.id or message.role != "assistant":
        raise NotFoundError("Message not found")
    clone = clone_service.get_chat_clone(db, conversation.clone_id, user)
    require_voice(clone, visitor=clone.owner_id != user.id)
    check_voice_rate(user.id)
    speech_audio = await generate_speech(
        message.content,
        effective_voice(clone),
        speech_language(clone, message.content),
        user_id=user.id,
        account_id=user.id,
        clone_id=clone.id,
        cache_key=str(message.id),  # "Play" again reuses the same recording
    )
    return audio_url(speech_audio.audio_id)


async def test_voice(clone: CloneProfile, user: User, text: str) -> str:
    require_voice(clone)
    check_voice_rate(user.id)
    speech_audio = await generate_speech(
        text, effective_voice(clone), clone.voice_language, user_id=user.id, account_id=user.id, clone_id=clone.id
    )
    return audio_url(speech_audio.audio_id)
