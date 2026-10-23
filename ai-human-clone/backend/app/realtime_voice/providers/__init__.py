"""Real-time voice providers by name (REALTIME_VOICE_PROVIDER)."""

from app.realtime_voice.provider_base import RealtimeProvider
from app.realtime_voice.providers.pipeline import PipelineProvider

PROVIDERS: dict[str, type[RealtimeProvider]] = {PipelineProvider.name: PipelineProvider}


def get_provider(name: str) -> RealtimeProvider | None:
    """The provider called `name`, or None when unknown (the feature then reports
    provider_not_configured instead of guessing)."""
    cls = PROVIDERS.get((name or "").strip().lower())
    return cls() if cls else None
