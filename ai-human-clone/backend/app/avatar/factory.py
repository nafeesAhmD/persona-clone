"""Chooses the lip-sync and avatar-image providers from settings.

LIPSYNC_PROVIDER: "local" (default, CPU), "fal" (photo-realistic, fal.ai cloud),
"http" (your own lip-sync server), or "none" (avatar videos off). To add a provider, implement the interfaces in
app/avatar/base.py and register it here.
"""

from functools import lru_cache

from app.avatar.base import AvatarProvider, LipSyncNotConfiguredError, LipSyncProvider
from app.avatar.providers.fal_lipsync import FalLipSync
from app.avatar.providers.http_lipsync import HttpLipSync
from app.avatar.providers.illustrated import IllustratedAvatarProvider
from app.avatar.providers.local_lipsync import LocalLipSync
from app.core.config import get_settings


@lru_cache
def get_lipsync_provider() -> LipSyncProvider:
    settings = get_settings()
    name = settings.lipsync_provider.strip().lower()
    if not settings.avatar_feature_enabled or name == "none":
        raise LipSyncNotConfiguredError("Avatar videos are turned off")
    if name == "local":
        return LocalLipSync()
    if name == "fal":
        return FalLipSync(
            settings.fal_api_key,
            settings.fal_lipsync_model,
            settings.fal_lipsync_resolution,
            settings.lipsync_timeout_seconds,
        )
    if name == "http":
        return HttpLipSync(settings.lipsync_api_url, settings.lipsync_api_key, settings.lipsync_timeout_seconds)
    raise LipSyncNotConfiguredError(f"Unknown LIPSYNC_PROVIDER '{name}'")


@lru_cache
def get_avatar_provider() -> AvatarProvider:
    return IllustratedAvatarProvider()


def lipsync_provider_name() -> str | None:
    try:
        return get_lipsync_provider().name
    except LipSyncNotConfiguredError:
        return None
