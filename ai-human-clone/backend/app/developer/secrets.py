"""Secret generation and hashing for API keys and webhook signing secrets.

API key:  "ahc_live_" + 43 url-safe characters (256 bits from `secrets`). Stored as
          HMAC-SHA256(pepper, key) only; looked up by that hash. The pepper comes
          from the server (JWT secret), so the hashes are useless without it.
Webhook:  the signing secret "whsec_..." is HMAC-SHA256(server key, webhook id + salt),
          re-derived when signing. Only the random salt and a hash are stored.
"""

import base64
import hashlib
import hmac
import secrets
import uuid

from app.core.security import _secret_key

KEY_PREFIX = "ahc_live_"
_DISPLAY_CHARS = 8


def _pepper(purpose: str) -> bytes:
    return hashlib.sha256(f"ahc-{purpose}:{_secret_key()}".encode()).digest()


def new_api_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(key: str) -> str:
    return hmac.new(_pepper("api-key"), key.encode(), hashlib.sha256).hexdigest()


def display_prefix(key: str) -> str:
    """What may be shown later: "ahc_live_Ab3dE6gH" (never enough to use the key)."""
    return key[: len(KEY_PREFIX) + _DISPLAY_CHARS]


def looks_like_api_key(value: str) -> bool:
    return value.startswith(KEY_PREFIX) and 30 <= len(value) <= 100


def new_webhook_salt() -> str:
    return secrets.token_hex(16)


def webhook_secret(webhook_id: uuid.UUID, salt: str) -> str:
    digest = hmac.new(_pepper("webhook"), f"{webhook_id}:{salt}".encode(), hashlib.sha256).digest()
    return "whsec_" + base64.urlsafe_b64encode(digest).decode().rstrip("=")


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def sign(secret: str, timestamp: int, body: bytes) -> str:
    """Signature for webhook consumers: HMAC-SHA256(secret, "{timestamp}.{body}") in hex."""
    message = f"{timestamp}.".encode() + body
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()

