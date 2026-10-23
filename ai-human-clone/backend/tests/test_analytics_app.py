"""Phase 15: the app's clone analytics (owner only): overview and daily activity."""

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AnalyticsEvent, CloneProfile
from tests.conftest import USER

CLONE = {"name": "Ayaan AI", "bio": "Developer", "owner_consent": True}
OTHER = {**USER, "email": "other@example.com", "username": "other", "full_name": "Other"}


def _clone(client: TestClient) -> str:
    response = client.post("/api/clones", json=CLONE)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_activity_lists_every_day_with_counts(client: TestClient, registered: dict, db_session: Session) -> None:
    clone_id = _clone(client)
    assert client.post(f"/api/clones/{clone_id}/chat", json={"message": "Hi there"}).status_code == 200
    clone_uuid = db_session.scalar(select(CloneProfile.id))
    db_session.add(AnalyticsEvent(clone_id=clone_uuid, event_type="chat_message", success=False,
                                  created_at=datetime.now(UTC)))
    db_session.commit()

    response = client.get(f"/api/clones/{clone_id}/analytics/activity?range=7d")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["range"] == "7d" and body["clone_id"] == clone_id
    days = body["days"]
    assert len(days) == 8  # 7 days back plus today
    assert days[-1]["date"] == date.today().isoformat() or days[-1]["date"] == datetime.now(UTC).date().isoformat()
    assert sum(d["conversations"] for d in days) == 1
    assert sum(d["messages"] for d in days) == 2  # question and answer
    assert sum(d["errors"] for d in days) == 1
    assert all(set(d) >= {"date", "conversations", "messages", "sessions", "errors"} for d in days)
    # Counts only: no message text.
    assert "Hi there" not in response.text

    today = client.get(f"/api/clones/{clone_id}/analytics/activity?range=today").json()["days"]
    assert len(today) == 1


def test_activity_rejects_unknown_ranges(client: TestClient, registered: dict) -> None:
    clone_id = _clone(client)
    assert client.get(f"/api/clones/{clone_id}/analytics/activity?range=1y").status_code in (400, 422)


def test_activity_and_overview_are_owner_only(client: TestClient, registered: dict, make_client) -> None:
    clone_id = _clone(client)
    other = make_client()
    assert other.post("/api/auth/register", json=OTHER).status_code == 201
    for path in ("activity", "overview"):
        assert other.get(f"/api/clones/{clone_id}/analytics/{path}?range=7d").status_code in (403, 404)
    assert make_client().get(f"/api/clones/{clone_id}/analytics/activity").status_code == 401


def test_overview_counts_messages(client: TestClient, registered: dict) -> None:
    clone_id = _clone(client)
    client.post(f"/api/clones/{clone_id}/chat", json={"message": "Hello"})
    body = client.get(f"/api/clones/{clone_id}/analytics/overview?range=30d").json()
    assert body["total_conversations"] == 1 and body["total_messages"] == 2


def test_activity_excludes_days_outside_range(client: TestClient, registered: dict, db_session: Session) -> None:
    clone_id = _clone(client)
    clone_uuid = db_session.scalar(select(CloneProfile.id))
    db_session.add(AnalyticsEvent(clone_id=clone_uuid, event_type="chat_message", success=False,
                                  created_at=datetime.now(UTC) - timedelta(days=60)))
    db_session.commit()
    days = client.get(f"/api/clones/{clone_id}/analytics/activity?range=30d").json()["days"]
    assert sum(d["errors"] for d in days) == 0
    days = client.get(f"/api/clones/{clone_id}/analytics/activity?range=90d").json()["days"]
    assert sum(d["errors"] for d in days) == 1
