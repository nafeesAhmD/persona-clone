"""The X-AHC-Signature header: "t=<unix seconds>,v1=<hex HMAC-SHA256>".

v1 = HMAC-SHA256(secret, f"{t}." + raw body). Consumers recompute it over the raw
request body, compare in constant time and reject timestamps older than the
tolerance (5 minutes by default) to stop replays.
"""

import hmac
import time

from app.developer.secrets import sign

SIGNATURE_HEADER = "X-AHC-Signature"
DEFAULT_TOLERANCE = 300


def signature_header(secret: str, timestamp: int, body: bytes) -> str:
    return f"t={timestamp},v1={sign(secret, timestamp, body)}"


def verify_signature(
    secret: str, header: str | None, body: bytes, tolerance: int = DEFAULT_TOLERANCE, *, now: float | None = None
) -> bool:
    """True when `header` is a valid, fresh signature of `body` made with `secret`."""
    if not header or not secret:
        return False
    timestamp: int | None = None
    candidates: list[str] = []
    for part in header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            try:
                timestamp = int(value)
            except ValueError:
                return False
        elif key == "v1" and value:
            candidates.append(value)
    if timestamp is None or not candidates:
        return False
    current = time.time() if now is None else now
    if tolerance is not None and tolerance >= 0 and abs(current - timestamp) > tolerance:
        return False
    expected = sign(secret, timestamp, body)
    return any(hmac.compare_digest(expected, candidate) for candidate in candidates)
