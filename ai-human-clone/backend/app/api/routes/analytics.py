import uuid
from datetime import date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.agent import access as agent_access
from app.analytics.metrics import parse_range
from app.analytics.schemas import AnalyticsOverview, DailyActivity
from app.analytics.service import AnalyticsService
from app.api.deps import CurrentUser, DbSession
from app.api.v1.analytics import (
    _as_date,  # the developer API's activity uses the same day parsing
)
from app.models import (
    AgentExecution,
    AgentStep,
    AnalyticsEvent,
    CloneProfile,
    Conversation,
    Message,
    PublicChatSession,
)
from app.schemas.agent import AgentAnalytics, AgentToolStat
from app.services import clone_service

router = APIRouter(prefix="/clones/{clone_id}/analytics", tags=["analytics"])


def _get_owned_clone(db: Session, clone_id: uuid.UUID, user: CurrentUser) -> CloneProfile:
    return clone_service.get_managed_clone(db, clone_id, user)


class CloneActivity(BaseModel):
    clone_id: uuid.UUID
    range: str
    start: datetime
    end: datetime
    days: list[DailyActivity]


def _per_day(db: Session, column, statement) -> dict[date, int]:
    day = func.date(column)
    return {_as_date(d): count for d, count in db.execute(statement.add_columns(day, func.count()).group_by(day))}


def daily_activity(db: Session, clone_id: uuid.UUID, start: datetime, end: datetime) -> list[DailyActivity]:
    """Per day (UTC): new conversations, messages, public visitor sessions and failed
    requests. Counts only, never content. Every day of the period is included."""
    conversations = _per_day(db, Conversation.created_at, select().select_from(Conversation).where(
        Conversation.clone_id == clone_id, Conversation.created_at >= start, Conversation.created_at < end))
    messages = _per_day(db, Message.created_at, select().select_from(Message).join(
        Conversation, Conversation.id == Message.conversation_id).where(
        Conversation.clone_id == clone_id, Message.created_at >= start, Message.created_at < end))
    sessions = _per_day(db, PublicChatSession.created_at, select().select_from(PublicChatSession).where(
        PublicChatSession.clone_id == clone_id, PublicChatSession.created_at >= start,
        PublicChatSession.created_at < end))
    errors = _per_day(db, AnalyticsEvent.created_at, select().select_from(AnalyticsEvent).where(
        AnalyticsEvent.clone_id == clone_id, AnalyticsEvent.success.is_(False),
        AnalyticsEvent.created_at >= start, AnalyticsEvent.created_at < end))
    days = []
    current = start.date()
    while current < end.date():
        days.append(DailyActivity(
            date=current, conversations=conversations.get(current, 0), messages=messages.get(current, 0),
            sessions=sessions.get(current, 0), errors=errors.get(current, 0),
        ))
        current += timedelta(days=1)
    return days


@router.get("/activity", response_model=CloneActivity)
def analytics_activity(
    clone_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    range: Annotated[Literal["today", "yesterday", "7d", "30d", "90d"], Query()] = "30d",
):
    """Daily activity of your clone for the app's charts (owner only)."""
    clone = _get_owned_clone(db, clone_id, user)
    start, end = parse_range(range)
    return CloneActivity(clone_id=clone.id, range=range, start=start, end=end,
                         days=daily_activity(db, clone.id, start, end))


@router.get("/overview", response_model=AnalyticsOverview)
def analytics_overview(
    clone_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    range: Annotated[str | None, Query()] = None,
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
):
    _get_owned_clone(db, clone_id, user)
    svc = AnalyticsService(db, clone_id)  # a UUID: a text id fails on databases without a native UUID type
    return svc.overview(range, start_date, end_date)


@router.get("/agent", response_model=AgentAnalytics, summary="AI agent analytics")
def analytics_agent(
    clone_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    range: Annotated[Literal["7d", "30d", "90d"], Query()] = "30d",
) -> AgentAnalytics:
    """Agent runs by outcome, average duration/steps and per-tool calls and failures
    (clone owner or organization owner/admin). Counts only, never goals or answers."""
    clone = agent_access.require_configure(db, user, clone_id, agent_access.ANALYTICS_DENIED)
    start, end = parse_range(range)
    in_range = (AgentExecution.clone_id == clone.id, AgentExecution.created_at >= start, AgentExecution.created_at < end)
    rows = db.execute(
        select(AgentExecution.status, AgentExecution.total_steps, AgentExecution.started_at, AgentExecution.completed_at)
        .where(*in_range)
    ).all()
    by_status: dict[str, int] = {}
    durations: list[float] = []
    for status, _, started, completed in rows:
        by_status[status] = by_status.get(status, 0) + 1
        if started is not None and completed is not None:
            delta = completed.replace(tzinfo=None) - started.replace(tzinfo=None)
            durations.append(max(delta.total_seconds() * 1000, 0))
    failed = func.sum(case((AgentStep.status == "failed", 1), else_=0))
    tool_rows = db.execute(
        select(AgentStep.tool_name, func.count(), failed)
        .join(AgentExecution, AgentExecution.id == AgentStep.execution_id)
        .where(*in_range, AgentStep.step_type == "tool", AgentStep.tool_name.is_not(None))
        .group_by(AgentStep.tool_name)
        .order_by(func.count().desc(), AgentStep.tool_name)
    ).all()
    tools = [
        AgentToolStat(tool=name, calls=calls, failures=int(fails or 0),
                      failure_rate=round(int(fails or 0) / calls, 3) if calls else 0.0)
        for name, calls, fails in tool_rows
    ]
    return AgentAnalytics(
        range=range,
        executions=len(rows),
        completed=by_status.get("completed", 0),
        failed=by_status.get("failed", 0),
        cancelled=by_status.get("cancelled", 0),
        timeout=by_status.get("timeout", 0),
        avg_duration_ms=round(sum(durations) / len(durations)) if durations else None,
        avg_steps=round(sum(r[1] or 0 for r in rows) / len(rows), 2) if rows else 0.0,
        tools=tools,
    )
