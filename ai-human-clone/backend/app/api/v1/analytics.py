"""Clone analytics through the API (scope analytics:read). Counts only, never content.

- GET /clones/{id}/analytics/overview?range=7d: totals for the period (reuses
  AnalyticsService.overview). If the analytics_events table doesn't exist in this
  database, the overview degrades to the counts that don't need it (conversations,
  messages, documents, memories, voice/avatar usage) instead of failing.
- GET /clones/{id}/analytics/activity?range=30d: conversations and messages per day.

Ranges: today, yesterday, 7d, 30d (default), 90d, as in the app; others are 400.
"""

import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from app.analytics.metrics import parse_range
from app.analytics.service import AnalyticsService
from app.api.deps import DbSession
from app.developer import access, feature_limits
from app.developer.auth import Scoped
from app.models import CloneMemory, CloneProfile, Conversation, Document, Message, PublicChatSession, UsageEvent
from app.schemas.api_v1 import ApiActivity, ApiActivityDay, ApiAnalyticsOverview

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Analytics"])

Range = Literal["today", "yesterday", "7d", "30d", "90d"]
RangeQuery = Annotated[Range, Query(description="Period: today, yesterday, 7d, 30d or 90d.")]
_has_events_table = False


def _events_table_exists(db: Session) -> bool:
    global _has_events_table
    if not _has_events_table:  # only a positive answer is cached: the table may be created later
        _has_events_table = inspect(db.get_bind()).has_table("analytics_events")
    return _has_events_table


def _count(db: Session, statement) -> int:
    return db.scalar(statement) or 0


def _basic_overview(db: Session, clone: CloneProfile, start: datetime, end: datetime) -> dict:
    """The overview's counts that come from the core tables (no analytics_events)."""

    def usage(*types: str) -> int:
        return _count(db, select(func.count()).select_from(UsageEvent).where(
            UsageEvent.clone_id == clone.id, UsageEvent.event_type.in_(types),
            UsageEvent.created_at >= start, UsageEvent.created_at < end,
        ))

    return {
        "total_conversations": _count(db, select(func.count()).select_from(Conversation).where(
            Conversation.clone_id == clone.id, Conversation.created_at >= start, Conversation.created_at < end)),
        "total_messages": _count(db, select(func.count()).select_from(Message).join(Conversation).where(
            Conversation.clone_id == clone.id, Message.created_at >= start, Message.created_at < end)),
        "total_public_sessions": _count(db, select(func.count()).select_from(PublicChatSession).where(
            PublicChatSession.clone_id == clone.id, PublicChatSession.created_at >= start,
            PublicChatSession.created_at < end)),
        "total_documents": _count(db, select(func.count()).select_from(Document).where(Document.clone_id == clone.id)),
        "total_memories": _count(db, select(func.count()).select_from(CloneMemory).where(
            CloneMemory.clone_id == clone.id)),
        "total_voice_requests": usage("STT_REQUEST", "TTS_REQUEST"),
        "total_avatar_requests": usage("AVATAR_JOB"),
        "total_usage_events": _count(db, select(func.count()).select_from(UsageEvent).where(
            UsageEvent.clone_id == clone.id, UsageEvent.created_at >= start, UsageEvent.created_at < end)),
    }


@router.get(
    "/clones/{clone_id}/analytics/overview", response_model=ApiAnalyticsOverview, summary="Analytics overview"
)
def overview(
    clone_id: uuid.UUID,
    request: Request,
    principal: Scoped("analytics:read"),
    db: DbSession,
    range: RangeQuery = "30d",  # noqa: A002 - the public query parameter name
) -> ApiAnalyticsOverview:
    """Totals for the period: conversations, messages, documents, memories, voice and
    avatar requests. Counts only. Scope: `analytics:read`."""
    clone = access.get_clone(db, principal, clone_id)
    feature_limits.mark_clone(request, clone)
    start, end = parse_range(range)
    counts = None
    if _events_table_exists(db):
        try:
            counts = AnalyticsService(db, str(clone.id)).overview(range).model_dump()
        except Exception:  # noqa: BLE001 - degrade to the basic counts rather than fail
            logger.warning("Analytics overview failed; returning basic counts", exc_info=True)
            db.rollback()
    if counts is None:
        counts = _basic_overview(db, clone, start, end)
    fields = set(ApiAnalyticsOverview.model_fields)
    return ApiAnalyticsOverview(
        clone_id=clone.id, range=range, start=start, end=end, **{k: v for k, v in counts.items() if k in fields}
    )


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


@router.get("/clones/{clone_id}/analytics/activity", response_model=ApiActivity, summary="Daily activity")
def activity(
    clone_id: uuid.UUID,
    request: Request,
    principal: Scoped("analytics:read"),
    db: DbSession,
    range: RangeQuery = "30d",  # noqa: A002 - the public query parameter name
) -> ApiActivity:
    """New conversations and messages per day (UTC) for the period, every day included.
    Counts only, never content. Scope: `analytics:read`."""
    clone = access.get_clone(db, principal, clone_id)
    feature_limits.mark_clone(request, clone)
    start, end = parse_range(range)

    conversation_day = func.date(Conversation.created_at)
    message_day = func.date(Message.created_at)
    conversations = {
        _as_date(day): count
        for day, count in db.execute(
            select(conversation_day, func.count())
            .where(Conversation.clone_id == clone.id, Conversation.created_at >= start, Conversation.created_at < end)
            .group_by(conversation_day)
        )
    }
    messages = {
        _as_date(day): count
        for day, count in db.execute(
            select(message_day, func.count())
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Conversation.clone_id == clone.id, Message.created_at >= start, Message.created_at < end)
            .group_by(message_day)
        )
    }
    days = []
    current = start.date()
    while current < end.date():
        days.append(ApiActivityDay(date=current, conversations=conversations.get(current, 0),
                                   messages=messages.get(current, 0)))
        current += timedelta(days=1)
    return ApiActivity(clone_id=clone.id, range=range, days=days)
