"""Security, usage and error events for the admin area.

Recording never slows down or breaks a request: events go to a queue that a
background thread writes in its own database session, and any failure is only
logged. What is stored is deliberately small:
- no request bodies, passwords, tokens, keys, prompts, documents or messages;
- detail values are short strings/numbers, and keys that look secret are dropped;
- IP addresses only on security events (admins only; SECURITY_LOG_RETENTION_DAYS).
"""

import logging
import queue
import re
import threading
import time
import traceback
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from starlette.requests import Request

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import ErrorEvent, SecurityEvent, UsageEvent

logger = logging.getLogger(__name__)

# Tests set this to write immediately instead of through the background thread.
INLINE = False
_SECRET_KEY = re.compile(r"pass|token|secret|key|auth|cookie|credential", re.IGNORECASE)
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_CLONE_PATH = re.compile(r"/api/clones/([0-9a-f-]{36})")
_queue: "queue.Queue[object]" = queue.Queue(maxsize=10_000)
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()
# Repeated events (e.g. one client hammering a rate limit) are stored once per window.
DEDUPE_SECONDS = 60.0
_recent: dict[str, float] = {}
_recent_lock = threading.Lock()


def _is_repeat(key: str) -> bool:
    now = time.monotonic()
    with _recent_lock:
        if len(_recent) > 5000:
            for old in [k for k, t in _recent.items() if now - t > DEDUPE_SECONDS]:
                del _recent[old]
        last = _recent.get(key)
        if last is not None and now - last < DEDUPE_SECONDS:
            return True
        _recent[key] = now
        return False


def reset_dedupe() -> None:
    with _recent_lock:
        _recent.clear()


def client_ip(request: Request | None) -> str | None:
    """The client address. X-Forwarded-For is used only when TRUST_PROXY_HEADERS is on.

    The last entry is the one our proxy appended; earlier entries come from the
    client and can be forged, so they are never trusted."""
    if request is None:
        return None
    if get_settings().trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[-1].strip()
        if forwarded:
            return forwarded[:64]
    return request.client.host[:64] if request.client else None


def safe_details(details: Mapping[str, object] | None) -> dict:
    clean: dict[str, object] = {}
    for key, value in (details or {}).items():
        if _SECRET_KEY.search(key):
            continue
        if isinstance(value, bool | int | float) or value is None:
            clean[key] = value
        else:
            clean[key] = str(value)[:200]
    return clean


def _write(row: object) -> None:
    try:
        with SessionLocal() as db:
            try:
                db.add(row)
                db.commit()
            except Exception:
                db.rollback()
                raise
    except Exception as exc:  # noqa: BLE001 - monitoring must never break the app
        logger.warning("Could not store a monitoring event: %s", type(exc).__name__)


def _run_worker() -> None:
    while True:
        row = _queue.get()
        _write(row)
        _queue.task_done()


def _submit(row: object) -> None:
    if INLINE:
        _write(row)
        return
    global _worker
    if _worker is None:
        with _worker_lock:
            if _worker is None:
                _worker = threading.Thread(target=_run_worker, name="monitoring-writer", daemon=True)
                _worker.start()
    try:
        _queue.put_nowait(row)
    except queue.Full:
        logger.warning("Monitoring queue full; dropping an event")


def flush(timeout: float = 5.0) -> bool:
    """Wait (at most `timeout` seconds) until queued events are written. Used by tests,
    the CLI and shutdown. False when events were still queued at the deadline."""
    if _worker is None:
        return True
    deadline = time.monotonic() + timeout
    while _queue.unfinished_tasks:
        if time.monotonic() >= deadline:
            logger.warning("Monitoring events still queued at shutdown: %d", _queue.unfinished_tasks)
            return False
        time.sleep(0.05)
    return True


# --- Recording ----------------------------------------------------------------------


def security(
    event_type: str,
    severity: str = "low",
    *,
    request: Request | None = None,
    user_id: uuid.UUID | None = None,
    details: Mapping[str, object] | None = None,
    dedupe: bool = False,
) -> None:
    if user_id is None and request is not None:
        user_id = getattr(request.state, "user_id", None)
    if dedupe and _is_repeat(f"{event_type}:{client_ip(request)}:{user_id}:{request.url.path if request else ''}"):
        return
    _submit(
        SecurityEvent(
            event_type=event_type,
            severity=severity,
            user_id=user_id,
            ip_address=client_ip(request),
            user_agent=(request.headers.get("user-agent") or "")[:300] if request is not None else None,
            details=safe_details({"path": request.url.path, **(details or {})} if request is not None else details),
            created_at=datetime.now(UTC),
        )
    )


def usage(
    event_type: str,
    *,
    provider: str | None = None,
    status: str = "success",
    user_id: uuid.UUID | None = None,
    clone_id: uuid.UUID | None = None,
    input_units: float | None = None,
    output_units: float | None = None,
    duration_ms: int | None = None,
    organization_id: uuid.UUID | None = None,
    api_key_id: uuid.UUID | None = None,
    endpoint: str | None = None,
    status_code: int | None = None,
) -> None:
    _submit(
        UsageEvent(
            event_type=event_type,
            provider=provider,
            status=status,
            user_id=user_id,
            clone_id=clone_id,
            input_units=input_units,
            output_units=output_units,
            duration_ms=duration_ms,
            organization_id=organization_id,
            api_key_id=api_key_id,
            endpoint=_UUID.sub("{id}", endpoint)[:200] if endpoint else None,
            status_code=status_code,
            created_at=datetime.now(UTC),
        )
    )


def estimated_tokens(*texts: str | None) -> float:
    """About four characters per token: an estimate, labelled as such in the admin area."""
    return round(sum(len(t or "") for t in texts) / 4, 1)


def _location(exc: BaseException) -> str | None:
    frames = traceback.extract_tb(exc.__traceback__)
    app_frames = [f for f in frames if "/app/" in f.filename.replace("\\", "/")] or frames
    if not app_frames:
        return None
    frame = app_frames[-1]
    module = frame.filename.replace("\\", "/").split("/app/", 1)[-1]
    return f"{module}:{frame.lineno} in {frame.name}"[:200]


def error(
    exc: BaseException,
    *,
    request: Request | None,
    status_code: int,
    category: str,
    message: str | None = None,
) -> None:
    """A server or provider error. Only the endpoint path (ids masked), never the body."""
    path = request.url.path if request is not None else None
    clone_match = _CLONE_PATH.search(path or "")
    try:
        clone_id = uuid.UUID(clone_match.group(1)) if clone_match else None
    except ValueError:
        clone_id = None
    _submit(
        ErrorEvent(
            error_type=type(exc).__name__[:80],
            category=category,
            method=request.method if request is not None else None,
            endpoint=_UUID.sub("{id}", path)[:300] if path else None,
            status_code=status_code,
            user_id=getattr(request.state, "user_id", None) if request is not None else None,
            clone_id=clone_id,
            message=(message or "")[:300] or None,
            location=_location(exc),
            request_id=getattr(request.state, "request_id", None) if request is not None else None,
            created_at=datetime.now(UTC),
        )
    )


# --- Retention ----------------------------------------------------------------------


def cleanup_old_logs() -> dict[str, int]:
    """Delete operational logs past their retention. Never touches users, clones or content."""
    settings = get_settings()
    now = datetime.now(UTC)
    removed: dict[str, int] = {}
    with SessionLocal() as db:
        for model, days in (
            (SecurityEvent, settings.security_log_retention_days),
            (UsageEvent, settings.usage_log_retention_days),
            (ErrorEvent, settings.error_log_retention_days),
        ):
            result = db.execute(delete(model).where(model.created_at < now - timedelta(days=days)))
            removed[model.__tablename__] = result.rowcount
        db.commit()
    if any(removed.values()):
        logger.info("Removed old monitoring logs: %s", removed)
    return removed
