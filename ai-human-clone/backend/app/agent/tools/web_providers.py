"""Web search providers for the web_search tool.

A provider turns a query into a short list of {title, url, snippet}. It must call ONE
fixed search API (no fetching of arbitrary pages). Providers register a factory under
a name; the active one is chosen by the AGENT_WEB_SEARCH_PROVIDER environment variable
(or a settings attribute `agent_web_search_provider` if one is added to config).

No provider ships configured: by default `get_provider()` returns None, so web_search
is unavailable even when AGENT_WEB_SEARCH_ENABLED=true. To add one, implement
WebSearchProvider, call register_provider("name", factory) at import time, and set
AGENT_WEB_SEARCH_PROVIDER=name. Every result goes through clean_results(): http(s)
URLs only, lengths capped, and the tool marks it as untrusted content.
"""

import os
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from app.core.config import get_settings

PROVIDER_ENV = "AGENT_WEB_SEARCH_PROVIDER"
TITLE_CHARS = 200
SNIPPET_CHARS = 300
URL_CHARS = 500


class WebSearchProvider(ABC):
    name: str = "provider"

    @abstractmethod
    def search(self, query: str, max_results: int) -> list[dict[str, str]]:
        """Return up to max_results dicts {title, url, snippet}. Raise on failure (the tool
        turns any error into a safe message)."""


_PROVIDERS: dict[str, Callable[[], WebSearchProvider]] = {}


def register_provider(name: str, factory: Callable[[], WebSearchProvider]) -> None:
    _PROVIDERS[name.strip().lower()] = factory


def unregister_provider(name: str) -> None:
    _PROVIDERS.pop(name.strip().lower(), None)


def configured_provider_name() -> str:
    value = getattr(get_settings(), "agent_web_search_provider", None) or os.environ.get(PROVIDER_ENV, "")
    return str(value).strip().lower()


def get_provider() -> WebSearchProvider | None:
    """The configured provider, or None if none is configured (the default) or it's unknown."""
    name = configured_provider_name()
    factory = _PROVIDERS.get(name) if name else None
    if factory is None:
        return None
    try:
        return factory()
    except Exception:  # noqa: BLE001 - a misconfigured provider just means "unavailable"
        return None


def _clip(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def safe_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    url = value.strip()
    if not url or len(url) > URL_CHARS or any(ch.isspace() for ch in url):
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    return url


def clean_results(raw: Any, max_results: int) -> list[dict[str, str]]:
    """Keep only well-formed results with http(s) URLs; cap count and lengths."""
    results: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return results
    for item in raw:
        if len(results) >= max_results:
            break
        if not isinstance(item, dict):
            continue
        url = safe_url(item.get("url"))
        if url is None:
            continue
        results.append(
            {
                "title": _clip(item.get("title"), TITLE_CHARS) or url,
                "url": url,
                "snippet": _clip(item.get("snippet"), SNIPPET_CHARS),
            }
        )
    return results
