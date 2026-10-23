"""Safety helpers for the agent: secret redaction, untrusted-data wrapping, safe previews.

Everything the agent stores (step metadata, results, errors, the final answer) and
everything it shows the planner from tools passes through `redact()`, which removes
secret-shaped strings (provider keys, JWTs, private keys, long random tokens, card
numbers) and the server's own configured secrets (API keys, JWT secret, database
URL...). Tool outputs, documents, memories, conversation text and web results are
wrapped with `untrusted()` so the planner treats them as data, never instructions.
"""

import json
import re
from typing import Any

from app.ai.rag_context import _neutralise
from app.core.config import get_settings
from app.services.memory_safety import _SECRET_SHAPES, looks_sensitive  # noqa: F401 - re-exported

REDACTED = "[redacted]"
UNTRUSTED_TAG = "untrusted_data"

# Long letter+digit runs without spaces: keys/tokens, not words.
_RANDOM_TOKEN = re.compile(r"(?=[A-Za-z0-9_\-]*[0-9])(?=[A-Za-z0-9_\-]*[A-Za-z])[A-Za-z0-9_\-]{32,}")
_BEARER = re.compile(r"(?i)\b(bearer|token|api[_-]?key|secret|password)\s*[:=]\s*\S+")
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_SECRET_SETTING = re.compile(r"key|secret|token|password|database_url|redis_url|dsn", re.IGNORECASE)
# Our own prompt markers inside untrusted text are defused so data can't close a block.
_OUR_TAGS = re.compile(r"</?\s*(untrusted_data|goal|agent_rules|system|tool_result|observations?)\b[^>]*>", re.IGNORECASE)


def _configured_secrets() -> list[str]:
    """The server's secret values (never shown to the planner or stored in results)."""
    values: list[str] = []
    settings = get_settings()
    for name, value in settings.__dict__.items():
        if not _SECRET_SETTING.search(name) or value is None:
            continue
        if hasattr(value, "get_secret_value"):
            value = value.get_secret_value()
        if isinstance(value, str) and len(value) >= 8:
            values.append(value)
    return sorted(values, key=len, reverse=True)


def redact(text: str | None) -> str:
    """Remove secret-looking strings and configured secrets from text."""
    if not text:
        return text or ""
    for secret in _configured_secrets():
        if secret in text:
            text = text.replace(secret, REDACTED)
    for pattern in _SECRET_SHAPES:
        text = pattern.sub(REDACTED, text)
    text = _BEARER.sub(lambda m: f"{m.group(1)}: {REDACTED}", text)
    text = _RANDOM_TOKEN.sub(lambda m: m.group(0) if _UUID.fullmatch(m.group(0)) else REDACTED, text)
    text = _CARD.sub(lambda m: REDACTED if len(re.sub(r"\D", "", m.group(0))) >= 13 else m.group(0), text)
    return text


def redact_data(value: Any) -> Any:
    """`redact()` applied to every string in a JSON-like structure."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {str(k): redact_data(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact_data(v) for v in value]
    return value


def short(text: str | None, limit: int = 200) -> str:
    """One safe line: redacted, whitespace collapsed, capped."""
    line = " ".join(redact(text or "").split())
    return line if len(line) <= limit else line[: limit - 1] + "…"


def input_preview(arguments: dict[str, Any], limit: int = 120) -> str:
    """A short, safe description of a tool's arguments for the confirmation card and logs."""
    try:
        text = json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        text = ", ".join(sorted(arguments))
    return short(text, limit)


def neutralise(text: str) -> str:
    """Defuse our prompt markers inside untrusted text."""
    text = _OUR_TAGS.sub(lambda m: m.group(0).replace("<", "(").replace(">", ")"), text)
    return _neutralise(text)


def untrusted(text: str, *, source: str) -> str:
    """Wrap untrusted text (tool output, document, memory, web page) as data."""
    label = re.sub(r"[^a-zA-Z0-9_:.\- ]", "", source)[:60]
    return f'<{UNTRUSTED_TAG} source="{label}">\n{neutralise(redact(text))}\n</{UNTRUSTED_TAG}>'
