"""Who may start real-time voice, and with which clone. Access to the clone itself
follows the normal chat rules (clone_service.get_chat_clone / public_service)."""

from app.core.config import get_settings
from app.models import CloneProfile
from app.realtime_voice.exceptions import RealtimeVoiceError
from app.realtime_voice.provider_base import RealtimeProvider
from app.realtime_voice.providers import get_provider


def active_provider() -> RealtimeProvider:
    """The configured provider. Raises realtime_disabled / provider_not_configured."""
    settings = get_settings()
    if not settings.realtime_voice_enabled:
        raise RealtimeVoiceError("realtime_disabled")
    provider = get_provider(settings.realtime_voice_provider)
    if provider is None or not provider.configured():
        raise RealtimeVoiceError("provider_not_configured")
    return provider


def clone_problem(clone: CloneProfile) -> str | None:
    """Why this clone can't hold a real-time conversation right now (None = it can)."""
    if not (clone.voice_enabled and clone.voice_consent_given):
        return "consent_missing"
    if not clone.realtime_voice_enabled:
        return "realtime_off"
    return None


def require_clone(clone: CloneProfile) -> None:
    problem = clone_problem(clone)
    if problem:
        raise RealtimeVoiceError(problem)


def public_allowed(clone: CloneProfile) -> bool:
    """Visitors: only when the owner turned it on, together with public chat and voice."""
    return bool(
        clone.public_realtime_voice_enabled
        and clone.public_chat_enabled
        and clone.public_voice_enabled
        and clone.visibility != "private"
        and clone.status == "active"
    )


def require_public(clone: CloneProfile) -> None:
    require_clone(clone)
    if not public_allowed(clone):
        raise RealtimeVoiceError("realtime_off")
