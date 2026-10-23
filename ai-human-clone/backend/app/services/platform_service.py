"""Platform-wide switches set by administrators (one platform_settings row).

Read on many requests (maintenance check, registration, discovery, public chat,
rate limits), so the values are cached in-process for a few seconds; a change
made through the admin API takes effect at once in this process and within
CACHE_SECONDS elsewhere. Provider keys and other secrets are never stored here.
"""

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models import PlatformSettings

logger = logging.getLogger(__name__)

CACHE_SECONDS = 5.0
# Rate limits an admin may override (per minute), and their settings names.
RATE_LIMIT_KEYS = {
    "login": "login_rate_limit_per_minute",
    "chat": "chat_rate_limit_per_minute",
    "public_chat": "public_chat_rate_limit_per_minute",
    "public_voice": "public_voice_rate_limit_per_minute",
    "public_avatar": "public_avatar_rate_limit_per_minute",
    "voice": "voice_rate_limit_per_minute",
    "avatar_video": "avatar_video_rate_limit_per_minute",
}


@dataclass(frozen=True)
class Snapshot:
    maintenance_mode: bool = False
    public_registration_enabled: bool = True
    public_clone_discovery_enabled: bool = True
    public_chat_enabled: bool = True
    rate_limits: dict = field(default_factory=dict)


_lock = threading.Lock()
_cached: Snapshot | None = None
_cached_at = 0.0


def _snapshot(row: PlatformSettings) -> Snapshot:
    return Snapshot(
        maintenance_mode=row.maintenance_mode,
        public_registration_enabled=row.public_registration_enabled,
        public_clone_discovery_enabled=row.public_clone_discovery_enabled,
        public_chat_enabled=row.public_chat_enabled,
        rate_limits={k: int(v) for k, v in (row.rate_limits or {}).items() if k in RATE_LIMIT_KEYS},
    )


def get_row(db: Session) -> PlatformSettings:
    row = db.get(PlatformSettings, 1)
    if row is None:  # e.g. a database created from the models (tests)
        row = PlatformSettings(id=1, rate_limits={})
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def current(db: Session) -> Snapshot:
    global _cached, _cached_at
    with _lock:
        if _cached is not None and time.monotonic() - _cached_at < CACHE_SECONDS:
            return _cached
    snapshot = _snapshot(get_row(db))
    with _lock:
        _cached, _cached_at = snapshot, time.monotonic()
    return snapshot


def cached() -> Snapshot:
    """The last known values without a database read (defaults before the first read)."""
    return _cached or Snapshot()


def invalidate() -> None:
    global _cached
    with _lock:
        _cached = None


def rate_limit(name: str, default: int) -> int:
    """An admin override for a per-minute rate limit, or the configured default."""
    return cached().rate_limits.get(name, default)


def update(db: Session, changes: dict, admin_id: uuid.UUID) -> tuple[PlatformSettings, dict]:
    """Apply changes; returns the row and {field: (before, after)} for what changed."""
    row = get_row(db)
    changed: dict[str, tuple] = {}
    for key, value in changes.items():
        if key == "rate_limits":
            merged = {k: v for k, v in (row.rate_limits or {}).items() if k in RATE_LIMIT_KEYS}
            for name, limit in value.items():
                if limit is None:
                    merged.pop(name, None)
                else:
                    merged[name] = int(limit)
            if merged != (row.rate_limits or {}):
                changed[key] = (row.rate_limits or {}, merged)
                row.rate_limits = merged
        elif getattr(row, key) != value:
            changed[key] = (getattr(row, key), value)
            setattr(row, key, value)
    if changed:
        row.updated_by = admin_id
    db.flush()
    invalidate()
    return row, changed
