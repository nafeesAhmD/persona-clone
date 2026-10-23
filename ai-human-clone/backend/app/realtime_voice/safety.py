"""Connection tickets, allowed origins and input limits for real-time voice."""

import hashlib
import hmac
import logging
import re
import secrets

from app.core.config import get_settings

TICKET_PREFIX = "rt_"
_TICKET_IN_TEXT = re.compile(r"(ticket=)[^&\s\"']+")


class RedactTicketFilter(logging.Filter):
    """Uvicorn logs each WebSocket request with its query string (…/ws?ticket=…).
    The ticket is short-lived and single-use, but still never belongs in a log."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "ticket=" in message:
            record.msg = _TICKET_IN_TEXT.sub(r"\1***", message)
            record.args = None
        return True


def install_log_redaction() -> None:
    for name in ("uvicorn.access", "uvicorn.error"):
        target = logging.getLogger(name)
        if not any(isinstance(f, RedactTicketFilter) for f in target.filters):
            target.addFilter(RedactTicketFilter())


def new_ticket() -> str:
    """A one-time WebSocket ticket. Only its hash is stored; it is never logged."""
    return TICKET_PREFIX + secrets.token_urlsafe(32)


def hash_ticket(ticket: str) -> str:
    return hashlib.sha256(ticket.encode()).hexdigest()


def ticket_matches(ticket: str | None, ticket_hash: str | None) -> bool:
    if not ticket or not ticket_hash or not ticket.startswith(TICKET_PREFIX) or len(ticket) > 100:
        return False
    return hmac.compare_digest(hash_ticket(ticket), ticket_hash)


def allowed_origins() -> list[str]:
    settings = get_settings()
    configured = [origin.rstrip("/") for origin in settings.realtime_voice_allowed_origins if origin and origin != "*"]
    return configured or settings.allowed_origins


def origin_allowed(origin: str | None) -> bool:
    """Browsers always send Origin on WebSockets; a missing or unknown one is refused."""
    return bool(origin) and origin.rstrip("/") in allowed_origins()


def utterance_ok(data: bytes) -> bool:
    return 0 < len(data) <= get_settings().realtime_voice_max_utterance_bytes


def clean_text(text: object) -> str | None:
    """A typed message: trimmed, non-empty and within the chat message limit."""
    if not isinstance(text, str):
        return None
    text = text.strip()
    if not text or len(text) > get_settings().max_chat_message_length:
        return None
    return text
