"""Client configuration for the mobile web / PWA (Phase 15): GET /api/mobile/config.

Public and safe: feature switches and limits the app needs to decide what to show
(e.g. hide the microphone when speech-to-text isn't configured). Never secrets,
keys, hosts or provider credentials; provider *names* only say whether a feature works.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import DbSession
from app.core.config import APP_VERSION, get_settings
from app.services import platform_service

router = APIRouter(prefix="/mobile", tags=["mobile"])


class VoiceConfig(BaseModel):
    speech_to_text: bool
    text_to_speech: bool
    max_recording_seconds: float
    max_audio_mb: int
    # The owner can clone their own voice (ElevenLabs key or the local voice-clone service).
    voice_cloning: bool = False
    # Phase 17: live voice conversations (REALTIME_VOICE_ENABLED and a provider configured).
    realtime_voice: bool = False


class AvatarConfig(BaseModel):
    enabled: bool
    videos: bool
    live_calls: bool
    max_image_mb: int
    max_video_seconds: float


class MobileConfig(BaseModel):
    app_name: str
    version: str
    maintenance_mode: bool
    registration_enabled: bool
    discovery_enabled: bool
    public_chat_enabled: bool
    billing_enabled: bool
    max_upload_mb: int
    voice: VoiceConfig
    avatar: AvatarConfig


def _realtime_available() -> bool:
    from app.realtime_voice import permissions
    from app.realtime_voice.exceptions import RealtimeVoiceError

    try:
        permissions.active_provider()
    except RealtimeVoiceError:
        return False
    except Exception:  # noqa: BLE001 - a config endpoint must not fail
        return False
    return True


@router.get("/config", response_model=MobileConfig)
def mobile_config(db: DbSession) -> MobileConfig:
    from app.avatar import live_avatar
    from app.avatar.factory import lipsync_provider_name
    from app.voice import routing
    from app.voice.factory import provider_status

    settings = get_settings()
    switches = platform_service.current(db)
    try:
        voice = provider_status()
    except Exception:  # noqa: BLE001 - a config endpoint must not fail
        voice = {"stt": None, "tts": None}
    return MobileConfig(
        app_name="Clone Me",
        version=APP_VERSION,
        maintenance_mode=switches.maintenance_mode,
        registration_enabled=switches.public_registration_enabled and not switches.maintenance_mode,
        discovery_enabled=switches.public_clone_discovery_enabled,
        public_chat_enabled=switches.public_chat_enabled,
        billing_enabled=settings.billing_enabled,
        max_upload_mb=settings.max_upload_size_mb,
        voice=VoiceConfig(
            speech_to_text=bool(voice.get("stt")),
            text_to_speech=bool(voice.get("tts")),
            max_recording_seconds=settings.max_audio_duration_seconds,
            max_audio_mb=settings.max_audio_size_mb,
            voice_cloning=routing.active_provider() is not None,
            realtime_voice=_realtime_available(),
        ),
        avatar=AvatarConfig(
            enabled=settings.avatar_feature_enabled,
            videos=settings.avatar_feature_enabled and lipsync_provider_name() is not None,
            live_calls=live_avatar.configured(),
            max_image_mb=settings.max_avatar_size_mb,
            max_video_seconds=settings.max_video_duration_seconds,
        ),
    )
