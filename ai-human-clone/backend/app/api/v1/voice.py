"""Voice through the API: speech to text, spoken chat, text to speech, and the audio.

- POST /clones/{id}/voice/transcribe (voice:transcribe): multipart `audio`.
- POST /clones/{id}/voice/chat (voice:transcribe + voice:tts + clone:chat): multipart
  `audio` and optional `conversation_id`; also counts toward monthly chat messages.
- POST /clones/{id}/voice/tts (voice:tts): {"text"} in the clone's voice.
- GET /clones/{id}/voice/audio/{audio_id} (voice:tts): the generated audio.

Calls run as the clone owner through voice_service, which enforces voice consent,
voice turned on and the per-user voice rate limit; this module adds the plan's monthly
voice_requests / tts_requests. Generated audio is returned as an API URL served here
(the internal /api/voice/audio route needs a browser session); file paths never leave
the server. Unconfigured voice providers give 503 provider_unavailable.
"""

import time
import uuid

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import DbSession
from app.developer import access, feature_limits, limits
from app.developer.auth import Scoped
from app.developer.errors import ApiError
from app.schemas.api_v1 import ApiAudio, ApiSource, ApiTranscription, ApiTtsRequest, ApiVoiceChatResponse
from app.services import voice_service
from app.voice.audio import max_audio_bytes, too_large_message
from app.voice.base import InvalidAudioError
from app.voice.storage import MIME_TYPES, get_voice_store

router = APIRouter(tags=["Voice"])


def audio_api_url(clone_id: uuid.UUID, internal_url: str | None) -> str | None:
    """Turn voice_service's internal audio URL into this API's download route."""
    if not internal_url:
        return None
    return f"/api/v1/clones/{clone_id}/voice/audio/{internal_url.rstrip('/').rsplit('/', 1)[-1]}"


async def _read_audio(audio: UploadFile) -> bytes:
    data = await audio.read(max_audio_bytes() + 1)  # never buffer an oversized upload
    if len(data) > max_audio_bytes():
        raise InvalidAudioError(too_large_message(), status_code=413)
    return data


def _conversation_id(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise ApiError(400, "invalid_request", "conversation_id must be a UUID.") from exc


def _elapsed(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


@router.post(
    "/clones/{clone_id}/voice/transcribe", response_model=ApiTranscription, summary="Speech to text"
)
async def transcribe(
    clone_id: uuid.UUID,
    request: Request,
    principal: Scoped("voice:transcribe"),
    db: DbSession,
    audio: UploadFile = File(..., description="WebM, WAV, MP3, M4A or OGG recording."),
) -> ApiTranscription:
    """Transcribe a recording in the language spoken. Scope: `voice:transcribe`.
    The clone must have voice turned on (with the owner's consent)."""
    clone = access.get_clone(db, principal, clone_id, for_use=True)
    feature_limits.mark_clone(request, clone)
    owner = access.acting_user(db, clone)
    voice_service.require_voice(clone)
    feature_limits.check(db, principal, owner.id, "voice_requests")
    started = time.monotonic()
    speech = await voice_service.transcribe(clone, owner, await _read_audio(audio), audio.filename, audio.content_type)
    feature_limits.record("API_VOICE", principal, request, clone, duration_ms=_elapsed(started),
                          input_units=speech.duration_seconds)
    return ApiTranscription(text=speech.text, language=speech.language, duration_seconds=speech.duration_seconds)


@router.post("/clones/{clone_id}/voice/chat", response_model=ApiVoiceChatResponse, summary="Spoken chat")
async def voice_chat(
    clone_id: uuid.UUID,
    request: Request,
    principal: Scoped("voice:transcribe", "voice:tts", "clone:chat"),
    db: DbSession,
    audio: UploadFile = File(..., description="The user's spoken message."),
    conversation_id: str | None = Form(default=None, description="Continue this conversation (optional)."),
) -> ApiVoiceChatResponse:
    """Transcription, then the normal chat turn, then the spoken answer. If speech generation
    fails, the text answer is still returned with `audio_url: null` and `tts_error`.
    Scopes: `voice:transcribe`, `voice:tts` and `clone:chat`."""
    clone = access.get_clone(db, principal, clone_id, for_use=True)
    feature_limits.mark_clone(request, clone)
    owner = access.acting_user(db, clone)
    conversation = _conversation_id(conversation_id)
    if conversation is not None:
        _, conversation_clone = access.get_conversation(db, principal, conversation)
        if conversation_clone.id != clone.id:
            raise ApiError(404, "resource_not_found", "Conversation not found.")
    voice_service.require_voice(clone)
    limits.check_chat_messages(
        db, acting_user_id=owner.id, user_id=principal.user_id, organization_id=principal.organization_id
    )
    feature_limits.check(db, principal, owner.id, "voice_requests", "tts_requests")
    started = time.monotonic()
    reply = await voice_service.voice_chat(
        db, clone, owner, await _read_audio(audio), audio.filename, audio.content_type, conversation, source="api"
    )
    feature_limits.record("API_VOICE", principal, request, clone, duration_ms=_elapsed(started),
                          input_units=reply.duration_seconds)
    feature_limits.record("API_CHAT", principal, request, clone, duration_ms=_elapsed(started))
    return ApiVoiceChatResponse(
        conversation_id=reply.conversation_id,
        message_id=reply.message.id,
        transcript=reply.transcript,
        answer=reply.answer,
        audio_url=audio_api_url(clone.id, reply.audio_url),
        tts_error=reply.tts_error,
        language=reply.language,
        duration_seconds=reply.duration_seconds,
        sources=[ApiSource(title=source.title, score=round(source.score, 4)) for source in reply.sources],
        memories_used=reply.memories_used,
    )


@router.post("/clones/{clone_id}/voice/tts", response_model=ApiAudio, summary="Text to speech")
async def text_to_speech(
    clone_id: uuid.UUID, data: ApiTtsRequest, request: Request, principal: Scoped("voice:tts"), db: DbSession
) -> ApiAudio:
    """Speak `text` in the clone's AI voice. Returns an `audio_url` to download with the
    same key. Scope: `voice:tts`."""
    clone = access.get_clone(db, principal, clone_id, for_use=True)
    feature_limits.mark_clone(request, clone)
    owner = access.acting_user(db, clone)
    voice_service.require_voice(clone)
    feature_limits.check(db, principal, owner.id, "tts_requests")
    started = time.monotonic()
    internal = await voice_service.test_voice(clone, owner, data.text)
    feature_limits.record("API_VOICE", principal, request, clone, duration_ms=_elapsed(started),
                          input_units=len(data.text))
    return ApiAudio(audio_url=audio_api_url(clone.id, internal))


@router.get(
    "/clones/{clone_id}/voice/audio/{audio_id}",
    response_class=FileResponse,
    summary="Download generated audio",
    responses={200: {"content": {"audio/mpeg": {}, "audio/wav": {}}, "description": "The audio file."}},
)
def get_audio(clone_id: uuid.UUID, audio_id: str, request: Request, principal: Scoped("voice:tts"), db: DbSession):
    """Audio generated through this API for the clone, until it expires. Scope: `voice:tts`."""
    clone = access.get_clone(db, principal, clone_id)
    feature_limits.mark_clone(request, clone)
    path = get_voice_store().find(clone.owner_id, audio_id)
    if path is None:
        raise ApiError(404, "resource_not_found", "Audio not found or expired.")
    return FileResponse(path, media_type=MIME_TYPES[path.suffix.lstrip(".")], headers={"Cache-Control": "no-store"})
