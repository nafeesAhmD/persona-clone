"""Monthly voice / avatar plan limits for the developer API, plus API usage records.

The plan is the key owner's plan (limits.plan_slug): a personal key uses its user's
plan, an organization key its organization's. Usage is counted from the existing
UsageEvent rows the voice and avatar services already write for the acting user (the
clone owner), so API calls and the owner's own use share one monthly allowance:

- voice_requests: STT_REQUEST (speech to text)
- tts_requests:   TTS_REQUEST (text to speech)
- avatar_requests: AVATAR_JOB (talking-avatar videos)

A limit of 0 (or missing) means unlimited, like the other plan limits.
"""

import uuid

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.developer import limits
from app.developer.auth import ApiPrincipal
from app.developer.errors import ApiError
from app.models import CloneProfile, UsageEvent
from app.services import monitoring

_EVENTS = {
    "voice_requests": "STT_REQUEST",
    "tts_requests": "TTS_REQUEST",
    "avatar_requests": "AVATAR_JOB",
}


def used_this_month(db: Session, event_type: str, acting_user_id: uuid.UUID) -> int:
    return db.scalar(
        select(func.count())
        .select_from(UsageEvent)
        .where(
            UsageEvent.event_type == event_type,
            UsageEvent.user_id == acting_user_id,
            UsageEvent.created_at >= limits.month_start(),
        )
    ) or 0


def check(db: Session, principal: ApiPrincipal, acting_user_id: uuid.UUID, *names: str) -> None:
    """Raise 429 usage_limit_reached if any of the named plan limits is used up."""
    slug = limits.plan_slug(db, user_id=principal.user_id, organization_id=principal.organization_id)
    plan = limits.plan_limits(db, slug)
    for name in names:
        limit = int(plan.get(name, 0) or 0)
        if limit <= 0:
            continue
        used = used_this_month(db, _EVENTS[name], acting_user_id)
        if used >= limit:
            raise ApiError(429, "usage_limit_reached", f"Monthly {name.replace('_', ' ')} limit reached ({limit}).")


def mark_clone(request: Request, clone: CloneProfile) -> None:
    """The generic API_REQUEST / API_ERROR event of this call gets the clone id."""
    request.state.api_clone_id = clone.id


def record(
    event_type: str,
    principal: ApiPrincipal,
    request: Request,
    clone: CloneProfile,
    *,
    status: str = "success",
    duration_ms: int | None = None,
    input_units: float | None = None,
    output_units: float | None = None,
) -> None:
    """An API_CHAT / API_SEARCH / API_VOICE / API_AVATAR usage event: sizes and ids only."""
    monitoring.usage(
        event_type,
        status=status,
        user_id=principal.user_id,
        organization_id=principal.organization_id,
        api_key_id=principal.key_id,
        clone_id=clone.id,
        duration_ms=duration_ms,
        input_units=input_units,
        output_units=output_units,
        endpoint=f"{request.method} {request.url.path}",
    )
