"""Webhooks (Phase 14): signed event notifications to URLs that developers register.

`emit()` is the one entry point the rest of the app calls. It never blocks on the
network and never raises into the caller's request: it only queues delivery rows,
and a background worker sends them (app/developer/webhooks/delivery.py).

Modules:
- events.py    - the subscribable events and their descriptions
- ssrf.py      - URL rules (https, no private/internal targets), checked at save and per send
- signature.py - X-AHC-Signature header and verify_signature() for consumers/tests
- service.py   - endpoint CRUD and ownership (personal or organization owner/admin)
- delivery.py  - queueing, sending, retries with backoff, the worker thread
"""

import logging
import uuid

from app.developer.webhooks.delivery import emit, process_due, start_worker, stop_worker, wake
from app.developer.webhooks.events import EVENT_DESCRIPTIONS, EVENTS, TEST_EVENT
from app.developer.webhooks.signature import verify_signature

logger = logging.getLogger(__name__)

__all__ = [
    "EVENTS",
    "EVENT_DESCRIPTIONS",
    "TEST_EVENT",
    "emit",
    "emit_for_clone",
    "process_due",
    "start_worker",
    "stop_worker",
    "verify_signature",
    "wake",
]


def emit_for_clone(
    event_type: str, data: dict, *, owner_id: uuid.UUID | None, organization_id: uuid.UUID | None = None
) -> None:
    """Send a clone event to the owner's personal webhooks and, for an organization's
    clone, to the organization's webhooks. Never raises."""
    try:
        emit(event_type, data, user_id=owner_id, organization_id=organization_id)
    except Exception as exc:  # noqa: BLE001 - emit already swallows errors; belt and braces
        logger.warning("Webhook event %s not queued: %s", event_type, type(exc).__name__)
