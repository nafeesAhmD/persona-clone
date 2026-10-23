"""Optional anti-abuse challenge for public visitors (off by default).

Vendor-neutral: Cloudflare Turnstile, hCaptcha and Google reCAPTCHA all verify a
widget token with the same "siteverify" call (form fields `secret`, `response`,
optional `remoteip`; JSON reply with `success`). Configure
PUBLIC_CAPTCHA_ENABLED=true, PUBLIC_CAPTCHA_VERIFY_URL and PUBLIC_CAPTCHA_SECRET;
the frontend then sends the widget's token as `captcha_token`. It is checked when
a visitor session starts, not on every message.
"""

import logging

import httpx

from app.core.config import get_settings
from app.services.errors import ForbiddenError

logger = logging.getLogger(__name__)

FAILED = "Please complete the verification challenge and try again."


def verify(token: str | None, remote_ip: str | None, *, transport: httpx.BaseTransport | None = None) -> None:
    """Raise ForbiddenError unless the challenge passed (no-op when CAPTCHA is off)."""
    settings = get_settings()
    if not settings.public_captcha_enabled:
        return
    if not settings.public_captcha_verify_url or not settings.public_captcha_secret:
        logger.error("PUBLIC_CAPTCHA_ENABLED is on but no verify URL/secret is configured")
        raise ForbiddenError("Verification is not available right now.")
    if not token:
        raise ForbiddenError(FAILED)
    data = {"secret": settings.public_captcha_secret, "response": token}
    if remote_ip:
        data["remoteip"] = remote_ip
    try:
        with httpx.Client(timeout=10, transport=transport) as client:
            reply = client.post(settings.public_captcha_verify_url, data=data).json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("CAPTCHA verification failed to run: %s", type(exc).__name__)
        raise ForbiddenError("Verification is not available right now.") from exc
    if not (isinstance(reply, dict) and reply.get("success") is True):
        raise ForbiddenError(FAILED)
