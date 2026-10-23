"""Voice: transcription, voice chat, settings, test, and generated audio.

Every route requires login. Transcribe and voice chat follow the chat access
rules (clone_service.get_chat_clone) and need voice turned on; settings and
the voice test are owner only. Generated audio can only be fetched by the
user it was generated for.
"""

import uuid

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.schemas.voice import (
    TranscriptionResponse,
    VoiceChatResponse,
    VoiceCloneStatus,
    VoiceCloneUpdate,
    VoiceSettingsRead,
    VoiceSettingsUpdate,
    VoiceTestRequest,
    VoiceTestResponse,
)
from app.services import clone_service, voice_clone_service, voice_service
from app.services.errors import InvalidInputError, NotFoundError
from app.services.rate_limit import check_voice_rate
from app.voice.audio import max_audio_bytes, too_large_message
from app.voice.base import InvalidAudioError
from app.voice.storage import MIME_TYPES, get_voice_store

router = APIRouter(tags=["voice"])


async def _read_audio(audio: UploadFile) -> bytes:
    # Read at most one byte past the limit: never buffer an oversized upload.
    data = await audio.read(max_audio_bytes() + 1)
    if len(data) > max_audio_bytes():
        raise InvalidAudioError(too_large_message(), status_code=413)
    return data


def _conversation_id(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise InvalidInputError("conversation_id must be a UUID") from exc


@router.post("/clones/{clone_id}/voice/transcribe", response_model=TranscriptionResponse)
async def transcribe(
    clone_id: uuid.UUID, user: CurrentUser, db: DbSession, audio: UploadFile = File(...)
) -> TranscriptionResponse:
    """Speech to text in the language spoken (WebM, WAV, MP3, M4A or OGG)."""
    clone = clone_service.get_chat_clone(db, clone_id, user)
    speech = await voice_service.transcribe(clone, user, await _read_audio(audio), audio.filename, audio.content_type)
    return TranscriptionResponse(text=speech.text, language=speech.language, duration_seconds=speech.duration_seconds)


@router.post("/clones/{clone_id}/voice/chat", response_model=VoiceChatResponse)
async def voice_chat(
    clone_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    audio: UploadFile = File(...),
    conversation_id: str | None = Form(default=None),
) -> VoiceChatResponse:
    """Speak to the clone: transcription, then the normal chat turn (knowledge, memory,
    saved messages), then the spoken answer. If speech generation fails, the text
    answer is returned with `audio_url: null` and `tts_error`."""
    clone = clone_service.get_chat_clone(db, clone_id, user)
    return await voice_service.voice_chat(
        db, clone, user, await _read_audio(audio), audio.filename, audio.content_type, _conversation_id(conversation_id)
    )


@router.get("/clones/{clone_id}/voice/settings", response_model=VoiceSettingsRead)
def get_voice_settings(clone_id: uuid.UUID, user: CurrentUser, db: DbSession) -> VoiceSettingsRead:
    return voice_service.settings_of(clone_service.get_managed_clone(db, clone_id, user))


@router.patch("/clones/{clone_id}/voice/settings", response_model=VoiceSettingsRead)
def update_voice_settings(
    clone_id: uuid.UUID, data: VoiceSettingsUpdate, user: CurrentUser, db: DbSession
) -> VoiceSettingsRead:
    """Turning voice on needs `voice_consent_given` first; withdrawing consent turns voice off."""
    clone = clone_service.get_managed_clone(db, clone_id, user)
    return voice_service.settings_of(voice_service.update_settings(db, clone, data))


@router.post("/clones/{clone_id}/voice/test", response_model=VoiceTestResponse)
async def test_voice(clone_id: uuid.UUID, data: VoiceTestRequest, user: CurrentUser, db: DbSession) -> VoiceTestResponse:
    """Hear the selected voice (owner only, voice on and consented)."""
    clone = clone_service.get_managed_clone(db, clone_id, user)
    return VoiceTestResponse(audio_url=await voice_service.test_voice(clone, user, data.text))


# --- Personal voice clone (owner only) ------------------------------------------------


@router.get("/clones/{clone_id}/voice/clone", response_model=VoiceCloneStatus)
def get_voice_clone(clone_id: uuid.UUID, user: CurrentUser, db: DbSession) -> VoiceCloneStatus:
    """The owner's cloned voice: whether cloning is available, its status and whether it's used."""
    return voice_clone_service.status_of(clone_service.get_managed_clone(db, clone_id, user))


@router.post("/clones/{clone_id}/voice/clone", response_model=VoiceCloneStatus, status_code=201)
async def create_voice_clone(
    clone_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    files: list[UploadFile] = File(...),
    consent: bool = Form(...),
    remove_background_noise: bool = Form(False),
) -> VoiceCloneStatus:
    """Clone the owner's voice from 1..VOICE_CLONE_MAX_FILES recordings (WebM, WAV, MP3, M4A
    or OGG; VOICE_CLONE_MIN_SECONDS..MAX_SECONDS in total). Needs voice consent on the clone and
    `consent=true` ("this is my own voice, or I have the speaker's permission"). The recordings
    are sent to the voice clone provider (ElevenLabs or the local service) and never stored. Replaces an existing cloned voice. A provider
    failure returns 201 with status "failed" and a safe `error`."""
    clone = clone_service.get_managed_clone(db, clone_id, user)
    voice_clone_service.require_available()
    if len(files) > get_settings().voice_clone_max_files:
        raise InvalidInputError(f"Use at most {get_settings().voice_clone_max_files} recordings.")
    check_voice_rate(user.id)
    samples = [(upload.filename, await _read_audio(upload), upload.content_type) for upload in files]
    return await voice_clone_service.create_clone(
        db, clone, samples, consent=consent, remove_background_noise=remove_background_noise
    )


@router.patch("/clones/{clone_id}/voice/clone", response_model=VoiceCloneStatus)
def update_voice_clone(clone_id: uuid.UUID, data: VoiceCloneUpdate, user: CurrentUser, db: DbSession) -> VoiceCloneStatus:
    """Speak with the cloned voice (only when it's ready) or go back to the prebuilt voice."""
    clone = clone_service.get_managed_clone(db, clone_id, user)
    return voice_clone_service.set_use(db, clone, data.use_cloned_voice)


@router.delete("/clones/{clone_id}/voice/clone", status_code=204)
def delete_voice_clone(clone_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    """Delete the cloned voice at its provider and here; the clone goes back to its prebuilt voice."""
    voice_clone_service.delete_clone_voice(db, clone_service.get_managed_clone(db, clone_id, user))


@router.post("/conversations/{conversation_id}/messages/{message_id}/speech", response_model=VoiceTestResponse)
async def speak_message(
    conversation_id: uuid.UUID, message_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> VoiceTestResponse:
    """Speech for one of the clone's answers in your own conversation (voice must be on)."""
    return VoiceTestResponse(audio_url=await voice_service.speak_message(db, user, conversation_id, message_id))


@router.get("/voice/audio/{audio_id}", response_class=FileResponse)
def get_audio(audio_id: str, user: CurrentUser) -> FileResponse:
    """Generated speech, for the user it was generated for, until it expires."""
    path = get_voice_store().find(user.id, audio_id)
    if path is None:
        raise NotFoundError("Audio not found or expired")
    return FileResponse(
        path, media_type=MIME_TYPES[path.suffix.lstrip(".")], headers={"Cache-Control": "no-store", "Vary": "Cookie"}  # never cached for the next user
    )
