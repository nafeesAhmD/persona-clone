from typing import Any

from app.models import AnalyticsEvent
from sqlalchemy.orm import Session


def record_event(
    db: Session,
    event_type: str,
    clone_id: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    source: str | None = None,
    metadata: dict[str, Any] | None = None,
    duration_ms: float | None = None,
    success: bool = True,
) -> AnalyticsEvent:
    event = AnalyticsEvent(
        user_id=user_id,
        clone_id=clone_id,
        session_id=session_id,
        event_type=event_type,
        source=source,
        metadata=metadata or {},
        duration_ms=duration_ms,
        success=success,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event
