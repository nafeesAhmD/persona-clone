"""Queueing and sending webhook deliveries.

The job model needs no extra infrastructure: the webhook_deliveries table *is* the
queue. `emit()` puts the event on a small in-memory queue and wakes the worker, so a
request never waits for the database or an HTTP call. The worker (a daemon thread,
see start_worker) writes queued events as "pending" rows - one per matching active
endpoint, in its own session - and repeatedly runs `process_due()`, which

1. claims due rows (pending with next_retry_at unset or past, or "delivering" rows
   whose lease ran out after a crash) - FOR UPDATE SKIP LOCKED on Postgres, so
   several app processes never send the same row twice;
2. for each: checks the URL again, resolves DNS again and refuses private targets,
   then POSTs the signed envelope to the checked address (no redirects followed);
3. 2xx = delivered. Anything else is retried with exponential backoff
   (30s, 60s, 120s, ... capped at 1h) until WEBHOOK_MAX_RETRIES attempts, then
   "failed". Every attempt carries the same event id, so consumers can dedupe.

A real queue (RQ/Celery/SQS) could later call `deliver_one(delivery_id)` instead of
the polling thread without changing the API or the table.

Tests: INLINE = True writes and delivers right away inside emit(); SYNC_WRITE = True
only writes the rows inside emit(); TRANSPORT injects an
httpx transport (e.g. httpx.MockTransport); CONCURRENCY = 1 keeps everything on
the calling thread.
"""

import json
import logging
import queue
import re
import secrets
import threading
import time
import uuid
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import httpx
from sqlalchemy import and_, or_, select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.developer.secrets import hash_secret, webhook_secret
from app.developer.webhooks import ssrf
from app.developer.webhooks.events import EVENTS, TEST_EVENT
from app.developer.webhooks.signature import signature_header
from app.models import WebhookDelivery, WebhookEndpoint

logger = logging.getLogger(__name__)

USER_AGENT = "AHC-Webhooks/1.0"
BACKOFF_BASE_SECONDS = 30
BACKOFF_MAX_SECONDS = 3600
BATCH_SIZE = 20
POLL_SECONDS = 5.0
# A claimed row is retried by another worker if not finished within this lease.
LEASE_EXTRA_SECONDS = 60

# Test switches. INLINE: emit() writes and sends on the calling thread.
# SYNC_WRITE: emit() writes the delivery rows on the calling thread; sending stays with process_due.
INLINE = False
SYNC_WRITE = False
TRANSPORT: httpx.BaseTransport | None = None
CONCURRENCY = 4

_SECRET_KEY = re.compile(r"pass|token|secret|key|auth|cookie|credential|prompt|content|text|path", re.IGNORECASE)
# usage.limit_reached can fire on every request once a limit is hit: send it once an hour.
_REPEAT_WINDOW = {"usage.limit_reached": 3600.0}
_recent: dict[tuple, float] = {}
_recent_lock = threading.Lock()
# Events waiting to be written as delivery rows by the worker (emit never touches the DB).
_events: "queue.Queue[tuple]" = queue.Queue(maxsize=10_000)


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def new_event_id() -> str:
    return "evt_" + secrets.token_urlsafe(18)


def backoff_seconds(attempts: int) -> int:
    """Wait after the `attempts`-th failed attempt: 30s, 60s, 120s, ... capped at 1 hour."""
    return min(BACKOFF_BASE_SECONDS * 2 ** max(0, attempts - 1), BACKOFF_MAX_SECONDS)


def max_attempts() -> int:
    return max(1, get_settings().webhook_max_retries)


def _clean_value(value):
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, list | tuple | set):
        return [_clean_value(item) for item in list(value)[:50] if not isinstance(item, Mapping)]
    return str(value)[:200]


def clean_data(data: Mapping | None) -> dict:
    """Event data: scalars and short lists only; keys that could carry secrets or text are dropped."""
    clean: dict = {}
    for key, value in (data or {}).items():
        key = str(key)[:60]
        if _SECRET_KEY.search(key) or isinstance(value, Mapping):
            continue
        clean[key] = _clean_value(value)
    return clean


def envelope(event_id: str, event_type: str, data: Mapping | None, at: datetime | None = None) -> dict:
    at = (at or _now()).astimezone(UTC)
    return {
        "id": event_id,
        "type": event_type,
        "timestamp": at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "data": clean_data(data),
    }


def encode_body(payload: Mapping) -> bytes:
    """The exact bytes that are signed and sent (stable across retries)."""
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False, sort_keys=True).encode()


def _is_repeat(event_type: str, user_id, organization_id, data: Mapping) -> bool:
    window = _REPEAT_WINDOW.get(event_type)
    if window is None:
        return False
    key = (event_type, user_id, organization_id, str(data.get("limit")))
    now = time.monotonic()
    with _recent_lock:
        last = _recent.get(key)
        if last is not None and now - last < window:
            return True
        if len(_recent) > 5000:
            _recent.clear()
        _recent[key] = now
        return False


def reset_dedupe() -> None:
    with _recent_lock:
        _recent.clear()


# --- Queueing -----------------------------------------------------------------


def queue_event(
    event_type: str,
    data: Mapping | None,
    *,
    user_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
    at: datetime | None = None,
) -> list[uuid.UUID]:
    """Insert one pending delivery per matching active endpoint. Returns their ids."""
    owners = []
    if user_id is not None:
        owners.append(WebhookEndpoint.user_id == user_id)
    if organization_id is not None:
        owners.append(WebhookEndpoint.organization_id == organization_id)
    if not owners:
        return []
    with SessionLocal() as db:
        try:
            endpoints = db.scalars(
                select(WebhookEndpoint).where(WebhookEndpoint.is_active.is_(True), or_(*owners))
            ).all()
            matching = [endpoint for endpoint in endpoints if event_type in (endpoint.events or [])]
            if not matching:
                return []
            now = _now()
            payload = envelope(new_event_id(), event_type, data, at or now)
            rows = [
                WebhookDelivery(
                    id=uuid.uuid4(),
                    webhook_id=endpoint.id,
                    event_id=payload["id"],
                    event_type=event_type,
                    payload=payload,
                    status="pending",
                    attempts=0,
                    created_at=now,
                )
                for endpoint in matching
            ]
            db.add_all(rows)
            db.commit()
            return [row.id for row in rows]
        except Exception:
            db.rollback()
            raise


def emit(
    event_type: str,
    data: dict,
    *,
    user_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
) -> None:
    """Queue `event_type` for the owner's matching webhooks. Never raises and never waits:
    the event goes to an in-memory queue that the worker writes as delivery rows and sends
    (SYNC_WRITE/INLINE write - and, for INLINE, send - on the calling thread instead)."""
    try:
        if not get_settings().webhook_delivery_enabled:
            return
        if event_type not in EVENTS:
            logger.warning("Ignoring unknown webhook event %s", event_type)
            return
        if user_id is None and organization_id is None:
            return
        if _is_repeat(event_type, user_id, organization_id, data or {}):
            return
        item = (event_type, clean_data(data), user_id, organization_id, _now())
        if INLINE or SYNC_WRITE:
            if _write_event(item):
                dispatch()
            return
        _events.put_nowait(item)
    except queue.Full:
        logger.warning("Webhook event queue full; dropping a %s event", event_type)
        return
    except Exception as exc:  # noqa: BLE001 - webhooks must never break the caller
        logger.warning("Could not queue webhook event %s: %s", event_type, type(exc).__name__)
        return
    wake()


def _write_event(item: tuple) -> list[uuid.UUID]:
    event_type, data, user_id, organization_id, at = item
    try:
        return queue_event(event_type, data, user_id=user_id, organization_id=organization_id, at=at)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not store webhook event %s: %s", event_type, type(exc).__name__)
        return []


def drain_events() -> int:
    """Write every queued event as delivery rows (run by the worker). Returns rows created."""
    created = 0
    while True:
        try:
            item = _events.get_nowait()
        except queue.Empty:
            return created
        created += len(_write_event(item))
        _events.task_done()


def pending_events() -> int:
    return _events.qsize()


def clear_events() -> None:
    while True:
        try:
            _events.get_nowait()
        except queue.Empty:
            return


def dispatch() -> None:
    """New work is waiting: deliver now (tests) or wake the worker."""
    if INLINE:
        try:
            process_due(transport=TRANSPORT)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Inline webhook delivery failed: %s", type(exc).__name__)
    else:
        wake()


# --- Sending ------------------------------------------------------------------


@dataclass
class Attempt:
    ok: bool
    status_code: int | None = None
    error: str | None = None


def _pinned_request(url: str, ip: str) -> tuple[httpx.URL, dict, dict]:
    target = httpx.URL(url)
    headers = {"Host": target.netloc.decode("ascii")}
    extensions: dict = {}
    if target.scheme == "https":
        try:
            import ipaddress

            ipaddress.ip_address(target.host)
        except ValueError:
            extensions["sni_hostname"] = target.host  # certificate is checked for the real name
    return target.copy_with(host=ip), headers, extensions


def send(
    url: str,
    payload: Mapping,
    secret: str,
    *,
    transport: httpx.BaseTransport | None = None,
    timeout: float | None = None,
) -> Attempt:
    """One signed POST. Re-validates the URL and DNS, pins the checked address, no redirects."""
    timeout = get_settings().webhook_timeout_seconds if timeout is None else timeout
    try:
        normalised, host, port = ssrf.parse(url)
        addresses = ssrf.resolve_safe(host, port)
    except ssrf.WebhookUrlError as exc:
        return Attempt(False, None, f"Blocked: {exc}"[:300])
    body = encode_body(payload)
    timestamp = int(time.time())
    target, headers, extensions = _pinned_request(normalised, addresses[0])
    headers.update(
        {
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "X-AHC-Event-Id": str(payload.get("id", "")),
            "X-AHC-Event-Type": str(payload.get("type", "")),
            "X-AHC-Signature": signature_header(secret, timestamp, body),
        }
    )
    try:
        with httpx.Client(
            transport=transport, timeout=httpx.Timeout(timeout), follow_redirects=False, trust_env=False
        ) as client:
            with client.stream("POST", target, content=body, headers=headers, extensions=extensions) as response:
                code = response.status_code  # the body is never read
    except httpx.TimeoutException:
        return Attempt(False, None, f"Timed out after {timeout:g}s")
    except httpx.HTTPError as exc:
        return Attempt(False, None, f"Connection failed ({type(exc).__name__})")
    except Exception as exc:  # noqa: BLE001
        return Attempt(False, None, f"Delivery error ({type(exc).__name__})")
    if 200 <= code < 300:
        return Attempt(True, code)
    if 300 <= code < 400:
        return Attempt(False, code, f"HTTP {code}: redirects are not followed")
    return Attempt(False, code, f"HTTP {code}")


def _claim(now: datetime, limit: int) -> list[uuid.UUID]:
    with SessionLocal() as db:
        try:
            due = or_(
                and_(
                    WebhookDelivery.status == "pending",
                    or_(WebhookDelivery.next_retry_at.is_(None), WebhookDelivery.next_retry_at <= now),
                ),
                and_(WebhookDelivery.status == "delivering", WebhookDelivery.next_retry_at <= now),
            )
            rows = db.scalars(
                select(WebhookDelivery)
                .where(due)
                .order_by(WebhookDelivery.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
            lease = now + timedelta(seconds=get_settings().webhook_timeout_seconds + LEASE_EXTRA_SECONDS)
            for row in rows:
                row.status = "delivering"
                row.next_retry_at = lease
            db.commit()
            return [row.id for row in rows]
        except Exception:
            db.rollback()
            raise


def deliver_one(
    delivery_id: uuid.UUID, *, now: datetime | None = None, transport: httpx.BaseTransport | None = None
) -> str | None:
    """Make one attempt for a claimed ("delivering") row. Returns the new status."""
    with SessionLocal() as db:
        delivery = db.get(WebhookDelivery, delivery_id)
        if delivery is None or delivery.status != "delivering":
            return None
        endpoint = db.get(WebhookEndpoint, delivery.webhook_id)
        problem = None
        secret = None
        if endpoint is None:
            problem = "The webhook was deleted."
        elif not endpoint.is_active and delivery.event_type != TEST_EVENT:
            problem = "The webhook is turned off."
        else:
            secret = webhook_secret(endpoint.id, endpoint.secret_salt)
            if hash_secret(secret) != endpoint.secret_hash:
                problem = "The signing secret is no longer valid. Rotate the secret."
                secret = None
        url = endpoint.url if endpoint is not None else ""
        payload = dict(delivery.payload or {})
        if problem is not None:
            delivery.status, delivery.last_error, delivery.next_retry_at = "failed", problem, None
            db.commit()
            return "failed"

    result = send(url, payload, secret, transport=transport)
    del secret

    with SessionLocal() as db:
        try:
            delivery = db.get(WebhookDelivery, delivery_id)
            if delivery is None:
                return None
            endpoint = db.get(WebhookEndpoint, delivery.webhook_id)
            at = now or _now()
            delivery.attempts = (delivery.attempts or 0) + 1
            delivery.response_status = result.status_code
            if endpoint is not None:
                endpoint.last_delivery_at = at
            if result.ok:
                delivery.status, delivery.delivered_at = "delivered", at
                delivery.last_error, delivery.next_retry_at = None, None
                if endpoint is not None:
                    endpoint.failure_count = 0
            else:
                delivery.last_error = (result.error or "Delivery failed")[:300]
                if endpoint is not None:
                    endpoint.failure_count = (endpoint.failure_count or 0) + 1
                    threshold = get_settings().webhook_auto_disable_after
                    if threshold > 0 and endpoint.failure_count >= threshold and endpoint.is_active:
                        # Stop hammering a dead endpoint; the owner re-enables it after fixing it.
                        endpoint.is_active = False
                        logger.warning("Webhook %s disabled after %d failed attempts", endpoint.id, endpoint.failure_count)
                if delivery.attempts >= max_attempts():
                    delivery.status, delivery.next_retry_at = "failed", None
                else:
                    delivery.status = "pending"
                    delivery.next_retry_at = at + timedelta(seconds=backoff_seconds(delivery.attempts))
            db.commit()
            if not result.ok:
                logger.info(
                    "Webhook delivery %s attempt %d failed: %s", delivery.id, delivery.attempts, delivery.last_error
                )
            return delivery.status
        except Exception:
            db.rollback()
            raise


def _safe_deliver(delivery_id: uuid.UUID, now: datetime | None, transport) -> str | None:
    try:
        return deliver_one(delivery_id, now=now, transport=transport)
    except Exception as exc:  # noqa: BLE001 - one bad row must not stop the others
        logger.warning("Webhook delivery %s crashed: %s", delivery_id, type(exc).__name__)
        return None


def process_due(
    now: datetime | None = None, transport: httpx.BaseTransport | None = None, *, limit: int = BATCH_SIZE
) -> int:
    """Send every due delivery once (one batch). Returns how many were attempted."""
    transport = transport if transport is not None else TRANSPORT
    claim_time = _aware(now) or _now()
    ids = _claim(claim_time, limit)
    if not ids:
        return 0
    at = _aware(now)
    if CONCURRENCY > 1 and len(ids) > 1:
        with ThreadPoolExecutor(max_workers=min(CONCURRENCY, len(ids)), thread_name_prefix="webhook-send") as pool:
            list(pool.map(lambda delivery_id: _safe_deliver(delivery_id, at, transport), ids))
    else:
        for delivery_id in ids:
            _safe_deliver(delivery_id, at, transport)
    return len(ids)


# --- Worker -------------------------------------------------------------------

_wake_event = threading.Event()
_stop_event = threading.Event()
_thread: threading.Thread | None = None
_thread_lock = threading.Lock()


def wake() -> None:
    """Ask the worker to look for due deliveries now instead of at the next poll."""
    _wake_event.set()


def _run() -> None:
    logger.info("Webhook delivery worker started")
    while not _stop_event.is_set():
        try:
            drain_events()
            # WEBHOOK_DELIVERY_ENABLED=false pauses sending too (queued rows wait).
            handled = process_due() if get_settings().webhook_delivery_enabled else 0
        except Exception as exc:  # noqa: BLE001 - e.g. the database is briefly down
            logger.warning("Webhook worker pass failed: %s", type(exc).__name__)
            handled = 0
        if handled >= BATCH_SIZE:
            continue  # more may be due right now
        _wake_event.wait(POLL_SECONDS)
        _wake_event.clear()
    drain_events()  # keep events emitted during shutdown; they are sent after the next start
    logger.info("Webhook delivery worker stopped")


def start_worker() -> None:
    """Start the background delivery thread (idempotent). Call once at app startup."""
    global _thread
    with _thread_lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop_event.clear()
        _thread = threading.Thread(target=_run, name="webhook-delivery", daemon=True)
        _thread.start()


def stop_worker(timeout: float = 5.0) -> None:
    """Stop the thread at app shutdown. Unsent rows stay queued for the next start."""
    global _thread
    with _thread_lock:
        thread, _thread = _thread, None
    if thread is None:
        return
    _stop_event.set()
    _wake_event.set()
    thread.join(timeout)


def worker_running() -> bool:
    return _thread is not None and _thread.is_alive()
