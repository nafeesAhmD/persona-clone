"""Phase 15: GET /api/billing/usage (real counts against the plan), plans and subscription."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing import service as billing_service
from app.core.config import get_settings
from app.models import CloneProfile, Conversation, Message, Subscription, UsageEvent, User
from tests.conftest import USER

CLONE = {"name": "Ayaan AI", "bio": "Developer", "owner_consent": True}
OTHER = {**USER, "email": "other@example.com", "username": "other", "full_name": "Other"}


@pytest.fixture
def owner(client: TestClient, registered: dict) -> TestClient:
    return client


def _user(db: Session, email: str = USER["email"]) -> User:
    return db.scalar(select(User).where(User.email == email.lower()))


def _items(body: dict) -> dict:
    return {item["key"]: item for item in body["items"]}


def test_usage_requires_login(client: TestClient) -> None:
    assert client.get("/api/billing/usage").status_code == 401


def test_free_mode_usage_has_every_limit_and_reset_date(owner: TestClient) -> None:
    response = owner.get("/api/billing/usage")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["plan_slug"] == "free" and body["plan_name"] == "Free" and body["billing_enabled"] is False
    items = _items(body)
    assert list(items) == [
        "chat_messages", "clones", "documents", "knowledge_mb", "voice_requests",
        "tts_requests", "avatar_requests", "public_chat_requests", "api_requests", "agent_executions",
    ]
    assert items["agent_executions"]["limit"] == 50
    assert items["chat_messages"]["limit"] == 1000 and items["chat_messages"]["used"] == 0
    assert items["clones"]["limit"] == 5 and items["clones"]["period"] == "total"
    assert items["knowledge_mb"]["unit"] == "MB"
    now = datetime.now(UTC)
    reset = datetime.fromisoformat(body["reset_at"].replace("Z", "+00:00"))
    assert reset.day == 1 and reset > now and reset - now <= timedelta(days=32)
    # Nothing about payments is ever exposed.
    text = response.text.lower()
    for secret in ("provider_customer_id", "provider_subscription_id", "secret", "stripe"):
        assert secret not in text


def test_usage_counts_this_month_for_this_user_only(owner: TestClient, make_client, db_session: Session) -> None:
    clone = owner.post("/api/clones", json=CLONE)
    assert clone.status_code == 201, clone.text
    clone_id = clone.json()["id"]
    note = {"title": "Notes", "content": "I build web services with Python and FastAPI every day."}
    assert owner.post(f"/api/clones/{clone_id}/knowledge", json=note).status_code == 201
    chat = owner.post(f"/api/clones/{clone_id}/chat", json={"message": "Hello?"})
    assert chat.status_code == 200, chat.text

    me = _user(db_session)
    clone_uuid = db_session.scalar(select(CloneProfile.id))
    last_month = datetime.now(UTC).replace(day=1) - timedelta(days=3)
    db_session.add_all([
        UsageEvent(user_id=me.id, clone_id=clone_uuid, event_type="STT_REQUEST", status="success"),
        UsageEvent(user_id=me.id, clone_id=clone_uuid, event_type="STT_REQUEST", status="success",
                   created_at=last_month),  # last month: not counted
        UsageEvent(user_id=me.id, clone_id=clone_uuid, event_type="TTS_REQUEST", status="success"),
        UsageEvent(user_id=me.id, clone_id=clone_uuid, event_type="AVATAR_JOB", status="success"),
        UsageEvent(clone_id=clone_uuid, event_type="PUBLIC_CHAT_MESSAGE", status="success"),
        UsageEvent(user_id=me.id, event_type="API_REQUEST", status="success"),
    ])
    # A message sent last month doesn't count toward this month.
    conversation = db_session.scalar(select(Conversation))
    db_session.add(Message(conversation_id=conversation.id, role="user", content="old", created_at=last_month))
    db_session.commit()

    items = _items(owner.get("/api/billing/usage").json())
    assert items["chat_messages"]["used"] == 1
    assert items["clones"]["used"] == 1
    assert items["documents"]["used"] == 1
    assert items["voice_requests"]["used"] == 1
    assert items["tts_requests"]["used"] == 1
    assert items["avatar_requests"]["used"] == 1
    assert items["public_chat_requests"]["used"] == 1
    assert items["api_requests"]["used"] == 1

    # Another account sees only its own usage.
    other = make_client()
    assert other.post("/api/auth/register", json=OTHER).status_code == 201
    other_items = _items(other.get("/api/billing/usage").json())
    assert all(item["used"] == 0 for item in other_items.values())


def test_plans_fall_back_to_builtin_plans_and_read_seeded_ones(client: TestClient, db_session: Session) -> None:
    builtin = client.get("/api/billing/plans")
    assert builtin.status_code == 200, builtin.text
    assert [p["slug"] for p in builtin.json()] == ["free", "pro", "business"]

    billing_service.seed_plans(db_session)
    seeded = client.get("/api/billing/plans")
    assert seeded.status_code == 200, seeded.text
    assert {p["slug"] for p in seeded.json()} == {"free", "pro", "business"}
    assert all(len(p["id"]) == 36 for p in seeded.json())  # database UUIDs as strings


def test_subscription_creates_free_plan_without_provider_ids(owner: TestClient, db_session: Session) -> None:
    assert owner.get("/api/billing/subscription").status_code == 404  # no plans in this database
    billing_service.seed_plans(db_session)
    response = owner.get("/api/billing/subscription")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "active" and body["user_id"] == str(_user(db_session).id)
    assert "provider_customer_id" not in body and "provider_subscription_id" not in body
    assert db_session.scalar(select(Subscription)) is not None


def test_billing_actions_are_forbidden_while_disabled(owner: TestClient) -> None:
    for path in ("/api/billing/checkout", "/api/billing/cancel", "/api/billing/portal"):
        assert owner.post(path).status_code == 403


def test_paid_plan_limits_when_billing_enabled(owner: TestClient, db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "billing_enabled", True)
    billing_service.seed_plans(db_session)
    me = _user(db_session)
    pro = db_session.scalar(select(billing_service.Plan).where(billing_service.Plan.slug == "pro"))
    db_session.add(Subscription(user_id=me.id, plan_id=pro.id, status="active", billing_cycle="month"))
    db_session.commit()
    body = owner.get("/api/billing/usage").json()
    assert body["plan_slug"] == "pro" and body["plan_name"] == "Pro" and body["billing_enabled"] is True
    assert _items(body)["chat_messages"]["limit"] == 5000


def test_usage_includes_agent_runs(client, registered) -> None:
    items = {item["key"]: item for item in client.get("/api/billing/usage").json()["items"]}
    assert items["agent_executions"]["used"] == 0
    assert items["agent_executions"]["label"] == "AI agent runs"
    assert items["agent_executions"]["period"] == "month"
