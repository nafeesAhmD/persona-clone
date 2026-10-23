import logging
from functools import lru_cache

from app.ai.base import LLMNotConfiguredError, LLMProvider
from app.ai.claude_service import ClaudeService
from app.ai.demo_service import DemoService
from app.ai.gemini_service import GeminiService
from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Register additional providers here (e.g. "openai": OpenAIService).
_PROVIDERS: dict[str, type[LLMProvider]] = {
    "claude": ClaudeService,
    "gemini": GeminiService,
    "demo": DemoService,
}


def _has_key(name: str, settings: Settings) -> bool:
    keys = {"claude": settings.anthropic_api_key, "gemini": settings.gemini_api_key}
    return name == "demo" or bool(keys.get(name))


def _resolve_provider_name(settings: Settings) -> str:
    requested = settings.llm_provider.lower()
    if requested != "auto":
        if requested not in _PROVIDERS:
            raise LLMNotConfiguredError(f"Unknown LLM_PROVIDER '{settings.llm_provider}'")
        if _has_key(requested, settings):
            return requested
        logger.warning("LLM_PROVIDER=%s has no API key; picking another provider", requested)

    for name in ("claude", "gemini"):
        if _has_key(name, settings):
            return name
    logger.warning("No LLM API key is set; chat runs in demo mode")
    return "demo"


@lru_cache
def get_llm_provider() -> LLMProvider:
    settings = get_settings()
    name = _resolve_provider_name(settings)
    logger.info("Using LLM provider: %s", name)
    return _PROVIDERS[name](settings)
