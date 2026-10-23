"""Phase 16: the AI agent API (profile, tools, runs, executions, access, analytics, developer API)."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AgentExecution, AgentStep, CloneProfile, Organization, OrganizationMember, User
from tests.conftest import USER

SARA = {**USER, "email": "sara@example.com", "username": "sara", "full_name": "Sara"}
OMAR = {**USER, "email": "omar@example.com", "username": "omar", "full_name": "Omar"}
CLONE = {
    "name": "Ayaan AI",
    "profession": "Software Developer",
    "skills": ["Python", "FastAPI"],
    "communication_style": "SECRET-STYLE-TEXT",
    "personality_description": "SECRET-PERSONALITY-TEXT",
    "owner_consent": True,
}
ANSWER = "Two plus two is 4."


# --- Fixtures and helpers ---------------------------------------------------------------


@pytest.fixture(autouse=True)
def _agent_platform_on(monkeypatch):
    """Most tests need AGENT_ENABLED=true; the off case sets it back explicitly."""
    from app.api.routes.agent import agent_run_limiter

    monkeypatch.setattr(get_settings(), "agent_enabled", True)
    monkeypatch.setattr(get_settings(), "api_rate_limit_per_minute", 1000)
    monkeypatch.setattr(get_settings(), "api_rate_limit_burst", 1000)
    agent_run_limiter.reset()
    yield
    agent_run_limiter.reset()


@pytest.fixture
def owner(client: TestClient, registered: dict) -> TestClient:
    return client


def _browser(make_client, data: dict) -> TestClient:
    browser = make_client()
    assert browser.post("/api/auth/register", json=data).status_code == 201
    return browser


@pytest.fixture
def sara(make_client) -> TestClient:
    return _browser(make_client, SARA)


@pytest.fixture
def omar(make_client) -> TestClient:
    return _browser(make_client, OMAR)


@pytest.fixture
def ext(make_client) -> TestClient:
    return make_client()


def new_clone(client: TestClient, **overrides) -> str:
    response = client.post("/api/clones", json={**CLONE, **overrides})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def enable(client: TestClient, clone_id: str, **extra) -> dict:
    response = client.patch(f"/api/clones/{clone_id}/agent", json={"enabled": True, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def plan(monkeypatch, llm, *decisions: dict) -> list[dict]:
    """Script the planner: each generate_json call returns the next decision, then a final answer."""
    queue = [json.dumps(d) for d in decisions]
    calls: list[dict] = []

    async def generate_json(system_prompt, user_message, schema):
        calls.append({"system": system_prompt, "message": user_message})
        if queue:
            return queue.pop(0)
        return json.dumps({"action": "final", "summary": "Answering", "answer": ANSWER})

    monkeypatch.setattr(llm, "generate_json", generate_json)
    return calls


CALC = {"action": "tool", "summary": "Calculating 2 + 2", "tool": "calculator", "arguments": {"expression": "2 + 2"}}
FINAL = {"action": "final", "summary": "Answering", "answer": ANSWER}


def run(client: TestClient, clone_id: str, goal: str = "What is 2 + 2?", **extra):
    return client.post(f"/api/clones/{clone_id}/agent/run", json={"goal": goal, **extra})


def started(client: TestClient, clone_id: str, **extra) -> dict:
    response = run(client, clone_id, **extra)
    assert response.status_code == 202, response.text
    execution = client.get(f"/api/agent/executions/{response.json()['execution_id']}")
    assert execution.status_code == 200, execution.text
    return execution.json()


def user_id(db: Session, email: str) -> uuid.UUID:
    return db.scalar(select(User.id).where(User.email == email.lower()))


def org_with(db: Session, clone_id: str, owner_email: str, members: dict[str, str]) -> Organization:
    """An organization owned by `owner_email` with `members` {email: role}; the clone joins it."""
    org = Organization(name="Acme", slug="acme", owner_id=user_id(db, owner_email), is_active=True)
    db.add(org)
    db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=org.owner_id, role="owner", status="active"))
    for email, role in members.items():
        db.add(OrganizationMember(organization_id=org.id, user_id=user_id(db, email), role=role, status="active"))
    clone = db.get(CloneProfile, uuid.UUID(clone_id))
    clone.organization_id = org.id
    db.commit()
    return org


def make_key(client: TestClient, scopes) -> str:
    response = client.post("/api/developer/keys", json={"name": "Agent bot", "scopes": list(scopes)})
    assert response.status_code == 201, response.text
    return response.json()["key"]


def api(client: TestClient, key: str, path: str, method: str = "GET", **kwargs):
    return client.request(method, path, headers={"Authorization": f"Bearer {key}"}, **kwargs)


def assert_api_error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["error"] == code and body["message"] and body["request_id"]


# --- Profile ------------------------------------------------------------------------------


def test_profile_defaults_are_off_and_conservative(owner: TestClient):
    clone_id = new_clone(owner)
    response = owner.get(f"/api/clones/{clone_id}/agent")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["clone_id"] == clone_id
    assert body["enabled"] is False
    assert body["public_agent_enabled"] is False
    assert body["allow_viewer_use"] is False
    assert body["require_confirmation_for_actions"] is True
    assert body["platform_enabled"] is True
    assert body["can_configure"] is True and body["can_run"] is True
    settings = get_settings()
    assert body["limits"] == {
        "max_steps": settings.agent_max_steps,
        "max_execution_time_seconds": settings.agent_max_execution_time_seconds,
        "max_tool_calls": settings.agent_max_tool_calls,
    }
    assert 1 <= body["max_steps"] <= settings.agent_max_steps
    tools = {t["name"]: t for t in body["tools"]}
    assert {"knowledge_search", "calculator", "date_time", "web_search"} <= set(tools)
    # Web search is off on this server: unavailable and never enabled.
    assert tools["web_search"]["available"] is False and tools["web_search"]["enabled"] is False
    assert tools["web_search"]["reason_unavailable"]
    for tool in tools.values():
        assert set(tool) >= {"name", "title", "description", "risk", "permission_scope", "enabled",
                             "require_confirmation", "available"}
    # No dangerous tools exist at all.
    assert not {"run_shell", "execute_command", "run_python", "read_env", "database_query"} & set(tools)


def test_enable_disable_and_patch_validation(owner: TestClient):
    clone_id = new_clone(owner)
    body = enable(owner, clone_id, name="Research helper", max_steps=3, max_execution_time_seconds=30)
    assert body["enabled"] is True and body["name"] == "Research helper"
    assert body["max_steps"] == 3 and body["max_execution_time_seconds"] == 30
    assert owner.patch(f"/api/clones/{clone_id}/agent", json={"enabled": False}).json()["enabled"] is False

    settings = get_settings()
    path = f"/api/clones/{clone_id}/agent"
    assert owner.patch(path, json={"max_steps": 0}).status_code == 400
    assert owner.patch(path, json={"max_steps": settings.agent_max_steps + 1}).status_code == 400
    assert owner.patch(path, json={"max_execution_time_seconds": 4}).status_code == 400
    too_long = settings.agent_max_execution_time_seconds + 1
    assert owner.patch(path, json={"max_execution_time_seconds": too_long}).status_code == 400
    # Mass assignment: unknown or protected fields are refused.
    for field in ({"owner_id": str(uuid.uuid4())}, {"clone_id": str(uuid.uuid4())}, {"id": "x"},
                  {"tools": []}, {"platform_enabled": True}, {"can_configure": True}):
        assert owner.patch(path, json=field).status_code == 400, field
    assert owner.get(path).json()["max_steps"] == 3


def test_tool_settings(owner: TestClient):
    clone_id = new_clone(owner)
    path = f"/api/clones/{clone_id}/agent/tools"
    response = owner.put(f"{path}/calculator", json={"enabled": False, "require_confirmation": True})
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "calculator"
    assert response.json()["enabled"] is False and response.json()["require_confirmation"] is True
    calc = next(t for t in owner.get(f"/api/clones/{clone_id}/agent").json()["tools"] if t["name"] == "calculator")
    assert calc["enabled"] is False and calc["require_confirmation"] is True
    # Omitting require_confirmation keeps it.
    assert owner.put(f"{path}/calculator", json={"enabled": True}).json()["require_confirmation"] is True

    # A tool this server can't offer can't be turned on.
    assert owner.put(f"{path}/web_search", json={"enabled": True, "require_confirmation": False}).status_code == 400
    # Tools that don't exist (and never will) are refused.
    for name in ("run_shell", "execute_command", "nope"):
        assert owner.put(f"{path}/{name}", json={"enabled": True, "require_confirmation": False}).status_code in (400, 404)
    assert owner.put(f"{path}/calculator", json={"enabled": True, "risk": "low"}).status_code == 400


# --- Runs ---------------------------------------------------------------------------------


def test_run_refused_when_platform_or_agent_off(owner: TestClient, monkeypatch):
    clone_id = new_clone(owner)
    off = run(owner, clone_id)
    assert off.status_code == 403 and off.json()["detail"] == "The AI agent is turned off for this clone."
    enable(owner, clone_id)
    monkeypatch.setattr(get_settings(), "agent_enabled", False)
    platform_off = run(owner, clone_id)
    assert platform_off.status_code == 403
    assert platform_off.json()["detail"] == "The AI agent isn't enabled on this server."
    assert owner.get(f"/api/clones/{clone_id}/agent").json()["platform_enabled"] is False


def test_run_validation(owner: TestClient):
    clone_id = new_clone(owner)
    enable(owner, clone_id)
    assert run(owner, clone_id, goal="").status_code == 400
    assert run(owner, clone_id, goal="x" * 4001).status_code == 400
    assert run(owner, clone_id, input_mode="video").status_code == 400
    assert run(owner, clone_id, user_id=str(uuid.uuid4())).status_code == 400
    assert run(owner, clone_id, conversation_id=str(uuid.uuid4())).status_code == 404


def test_run_success_and_execution_read(owner: TestClient, monkeypatch, llm, db_session: Session):
    clone_id = new_clone(owner)
    enable(owner, clone_id)
    plan(monkeypatch, llm, CALC, FINAL)
    response = run(owner, clone_id)
    assert response.status_code == 202, response.text
    assert set(response.json()) == {"execution_id", "status"}
    execution = owner.get(f"/api/agent/executions/{response.json()['execution_id']}").json()
    assert execution["status"] == "completed", execution
    assert execution["clone_id"] == clone_id and execution["goal"] == "What is 2 + 2?"
    assert execution["requires_confirmation"] is False and execution["pending_action"] is None
    assert execution["final_message_id"] and execution["conversation_id"]
    assert execution["tool_calls"] >= 1
    tool_steps = [s for s in execution["steps"] if s["step_type"] == "tool"]
    assert tool_steps and tool_steps[0]["tool_name"] == "calculator" and tool_steps[0]["status"] == "succeeded"
    for step in execution["steps"]:
        assert set(step) == {"step_number", "step_type", "tool_name", "status", "summary", "duration_ms", "created_at"}
    # Only contract fields: no hidden reasoning, raw metadata or internal flags.
    for hidden in ("input_metadata", "output_metadata", "reasoning", "cancel_requested", "api_key_id", "user_id"):
        assert hidden not in json.dumps(execution)
    row = db_session.get(AgentExecution, uuid.UUID(execution["id"]))
    assert row.user_id == user_id(db_session, USER["email"]) and row.source == "app"

    # Voice + agent: the final answer is a normal assistant message, so speech works on it.
    assert owner.patch(f"/api/clones/{clone_id}/voice/settings",
                       json={"voice_consent_given": True, "voice_enabled": True}).status_code == 200
    speech = owner.post(f"/api/conversations/{execution['conversation_id']}/messages/{execution['final_message_id']}/speech")
    assert speech.status_code == 200, speech.text
    assert owner.get(speech.json()["audio_url"]).status_code == 200


def test_speech_uses_the_agent_answer(owner: TestClient, monkeypatch, llm, tts):
    clone_id = new_clone(owner)
    enable(owner, clone_id)
    owner.patch(f"/api/clones/{clone_id}/voice/settings", json={"voice_consent_given": True, "voice_enabled": True})
    plan(monkeypatch, llm, FINAL)
    execution = started(owner, clone_id)
    response = owner.post(
        f"/api/conversations/{execution['conversation_id']}/messages/{execution['final_message_id']}/speech"
    )
    assert response.status_code == 200, response.text
    assert ANSWER in tts.calls[-1]["text"]


def test_list_executions_is_paginated(owner: TestClient, monkeypatch, llm):
    clone_id = new_clone(owner)
    enable(owner, clone_id)
    plan(monkeypatch, llm)
    ids = [started(owner, clone_id, goal=f"Goal {i} " + "y" * 300)["id"] for i in range(3)]
    page = owner.get(f"/api/clones/{clone_id}/agent/executions", params={"page": 1, "limit": 2}).json()
    assert page["total"] == 3 and page["page"] == 1 and page["limit"] == 2 and len(page["items"]) == 2
    item = page["items"][0]
    assert set(item) == {"id", "status", "goal", "total_steps", "created_at", "completed_at", "source"}
    assert len(item["goal"]) <= 200 and item["source"] == "app"
    second = owner.get(f"/api/clones/{clone_id}/agent/executions", params={"page": 2, "limit": 2}).json()
    assert len(second["items"]) == 1
    assert {i["id"] for i in page["items"] + second["items"]} == set(ids)
    assert owner.get(f"/api/clones/{clone_id}/agent/executions", params={"limit": 101}).status_code == 400


def test_run_rate_limit(owner: TestClient, monkeypatch, llm):
    from app.api.routes import agent as agent_routes

    monkeypatch.setattr(agent_routes, "RUN_RATE_PER_MINUTE", 2)
    clone_id = new_clone(owner)
    enable(owner, clone_id)
    plan(monkeypatch, llm)
    assert run(owner, clone_id).status_code == 202
    assert run(owner, clone_id).status_code == 202
    assert run(owner, clone_id).status_code == 429


def test_cancel(owner: TestClient, monkeypatch, llm):
    clone_id = new_clone(owner)
    enable(owner, clone_id)
    owner.put(f"/api/clones/{clone_id}/agent/tools/calculator", json={"enabled": True, "require_confirmation": True})
    plan(monkeypatch, llm, CALC, FINAL)
    execution = started(owner, clone_id)
    assert execution["status"] == "waiting_confirmation", execution
    cancelled = owner.post(f"/api/agent/executions/{execution['id']}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["pending_action"] is None


def test_confirmation_flow(owner: TestClient, monkeypatch, llm):
    clone_id = new_clone(owner)
    enable(owner, clone_id)
    owner.put(f"/api/clones/{clone_id}/agent/tools/calculator", json={"enabled": True, "require_confirmation": True})
    plan(monkeypatch, llm, CALC, FINAL)
    execution = started(owner, clone_id)
    assert execution["status"] == "waiting_confirmation" and execution["requires_confirmation"] is True
    action = execution["pending_action"]
    assert action["tool"] == "calculator" and action["action_id"]
    assert set(action) == {"action_id", "tool", "title", "reason", "risk", "input_preview"}

    base = f"/api/agent/executions/{execution['id']}"
    assert owner.post(f"{base}/confirm", json={"action_id": "wrong"}).status_code in (400, 409)
    assert owner.post(f"{base}/reject", json={"action_id": "wrong"}).status_code in (400, 409)
    assert owner.post(f"{base}/confirm", json={}).status_code == 400
    confirmed = owner.post(f"{base}/confirm", json={"action_id": action["action_id"]})
    assert confirmed.status_code == 200, confirmed.text
    final = owner.get(base).json()
    assert final["status"] == "completed", final
    # The same action can't be replayed.
    assert owner.post(f"{base}/confirm", json={"action_id": action["action_id"]}).status_code in (400, 409)


def test_reject_flow(owner: TestClient, monkeypatch, llm):
    clone_id = new_clone(owner)
    enable(owner, clone_id)
    owner.put(f"/api/clones/{clone_id}/agent/tools/calculator", json={"enabled": True, "require_confirmation": True})
    plan(monkeypatch, llm, CALC, FINAL)
    execution = started(owner, clone_id)
    action_id = execution["pending_action"]["action_id"]
    rejected = owner.post(f"/api/agent/executions/{execution['id']}/reject", json={"action_id": action_id})
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["pending_action"] is None
    assert any(s["status"] == "rejected" for s in owner.get(f"/api/agent/executions/{execution['id']}").json()["steps"])


# --- Access control -------------------------------------------------------------------------


def test_other_users_cannot_touch_the_agent_or_its_executions(owner: TestClient, sara: TestClient, monkeypatch, llm):
    clone_id = new_clone(owner)
    enable(owner, clone_id)
    owner.put(f"/api/clones/{clone_id}/agent/tools/calculator", json={"enabled": True, "require_confirmation": True})
    plan(monkeypatch, llm, CALC, FINAL)
    execution = started(owner, clone_id)
    base = f"/api/agent/executions/{execution['id']}"
    action_id = execution["pending_action"]["action_id"]

    # Private clone of someone else: invisible.
    assert sara.get(f"/api/clones/{clone_id}/agent").status_code == 404
    assert sara.patch(f"/api/clones/{clone_id}/agent", json={"enabled": False}).status_code == 404
    assert sara.put(f"/api/clones/{clone_id}/agent/tools/calculator",
                    json={"enabled": True, "require_confirmation": False}).status_code == 404
    assert run(sara, clone_id).status_code == 404
    assert sara.get(f"/api/clones/{clone_id}/agent/executions").status_code == 404
    assert sara.get(f"/api/clones/{clone_id}/analytics/agent").status_code == 404
    assert sara.get(base).status_code == 404
    assert sara.post(f"{base}/cancel").status_code == 404
    assert sara.post(f"{base}/confirm", json={"action_id": action_id}).status_code == 404
    assert sara.post(f"{base}/reject", json={"action_id": action_id}).status_code == 404
    assert sara.post(f"{base}/memory-proposal", json={"proposal_id": "x", "save": True}).status_code == 404
    assert sara.get(f"/api/agent/executions/{uuid.uuid4()}").status_code == 404
    # Still waiting for the owner.
    assert owner.get(base).json()["status"] == "waiting_confirmation"

    # A public clone of someone else: visible, but no agent rights (403).
    public_id = new_clone(owner, visibility="public")
    assert sara.get(f"/api/clones/{public_id}/agent").status_code == 403
    assert sara.patch(f"/api/clones/{public_id}/agent", json={"enabled": True}).status_code == 403
    assert run(sara, public_id).status_code == 403


def test_logged_out_is_refused(client: TestClient):
    clone_id = str(uuid.uuid4())
    assert client.get(f"/api/clones/{clone_id}/agent").status_code == 401
    assert client.post(f"/api/clones/{clone_id}/agent/run", json={"goal": "hi"}).status_code == 401
    assert client.get(f"/api/agent/executions/{clone_id}").status_code == 401


def test_organization_roles(owner, make_client, db_session: Session, monkeypatch, llm):
    clone_id = new_clone(owner)
    enable(owner, clone_id)
    admin = _browser(make_client, {**USER, "email": "admin@example.com", "username": "orgadmin"})
    editor = _browser(make_client, {**USER, "email": "editor@example.com", "username": "orgeditor"})
    viewer = _browser(make_client, {**USER, "email": "viewer@example.com", "username": "orgviewer"})
    outsider = _browser(make_client, {**USER, "email": "out@example.com", "username": "outsider"})
    org_owner = _browser(make_client, {**USER, "email": "boss@example.com", "username": "orgboss"})
    org_with(db_session, clone_id, "boss@example.com", {
        USER["email"]: "editor", "admin@example.com": "admin", "editor@example.com": "editor",
        "viewer@example.com": "viewer",
    })
    path = f"/api/clones/{clone_id}/agent"
    plan(monkeypatch, llm)

    # Org owner and admin configure and run.
    for browser in (org_owner, admin):
        body = browser.get(path).json()
        assert body["can_configure"] is True and body["can_run"] is True
        assert browser.patch(path, json={"max_steps": 4}).status_code == 200
        assert browser.put(f"{path}/tools/date_time", json={"enabled": True, "require_confirmation": False}).status_code == 200
        assert run(browser, clone_id).status_code == 202
        assert browser.get(f"/api/clones/{clone_id}/analytics/agent").status_code == 200
        # The public agent stays the clone owner's decision.
        assert browser.patch(path, json={"public_agent_enabled": True}).status_code == 403

    # Editor: runs, can't configure.
    body = editor.get(path).json()
    assert body["can_configure"] is False and body["can_run"] is True
    assert editor.patch(path, json={"max_steps": 2}).status_code == 403
    assert editor.put(f"{path}/tools/calculator", json={"enabled": False, "require_confirmation": False}).status_code == 403
    analytics = editor.get(f"/api/clones/{clone_id}/analytics/agent")
    assert analytics.status_code == 403 and "agent analytics" in analytics.json()["detail"]
    editor_run = started(editor, clone_id)
    assert editor_run["status"] == "completed"
    row = db_session.get(AgentExecution, uuid.UUID(editor_run["id"]))
    assert row.user_id == user_id(db_session, "editor@example.com")  # requester recorded
    # Editors list only their own runs; the owner sees everything.
    assert {i["id"] for i in editor.get(f"{path}/executions").json()["items"]} == {editor_run["id"]}
    assert owner.get(f"{path}/executions").json()["total"] == 3
    # The owner and org admins can read the editor's run; the viewer can't.
    assert owner.get(f"/api/agent/executions/{editor_run['id']}").status_code == 200
    assert admin.get(f"/api/agent/executions/{editor_run['id']}").status_code == 200
    assert viewer.get(f"/api/agent/executions/{editor_run['id']}").status_code == 404

    # Viewer: blocked until the owner allows viewer use.
    assert viewer.get(path).json()["can_run"] is False
    assert run(viewer, clone_id).status_code == 403
    assert viewer.patch(path, json={"allow_viewer_use": True}).status_code == 403
    assert owner.patch(path, json={"allow_viewer_use": True}).status_code == 200
    assert viewer.get(path).json()["can_run"] is True
    assert run(viewer, clone_id).status_code == 202

    # Non-member: the private clone doesn't exist for them.
    assert outsider.get(path).status_code == 404
    assert run(outsider, clone_id).status_code == 404


def test_confirm_needs_run_permission(owner, make_client, db_session: Session, monkeypatch, llm):
    """A viewer who started a run can't approve its actions once viewer use is turned off."""
    clone_id = new_clone(owner)
    enable(owner, clone_id, allow_viewer_use=True)
    owner.put(f"/api/clones/{clone_id}/agent/tools/calculator", json={"enabled": True, "require_confirmation": True})
    viewer = _browser(make_client, {**USER, "email": "viewer@example.com", "username": "orgviewer"})
    org_with(db_session, clone_id, USER["email"], {"viewer@example.com": "viewer"})
    plan(monkeypatch, llm, CALC, FINAL)
    execution = started(viewer, clone_id)
    action_id = execution["pending_action"]["action_id"]
    owner.patch(f"/api/clones/{clone_id}/agent", json={"allow_viewer_use": False})
    base = f"/api/agent/executions/{execution['id']}"
    assert viewer.get(base).status_code == 200  # still their own run
    assert viewer.post(f"{base}/confirm", json={"action_id": action_id}).status_code == 403
    assert viewer.post(f"{base}/reject", json={"action_id": action_id}).status_code == 403
    assert owner.post(f"{base}/confirm", json={"action_id": action_id}).status_code == 200


def test_public_agent_is_off_and_owner_only(owner: TestClient, db_session: Session):
    clone_id = new_clone(owner, visibility="public")
    assert owner.get(f"/api/clones/{clone_id}/agent").json()["public_agent_enabled"] is False
    assert db_session.get(CloneProfile, uuid.UUID(clone_id)).public_agent_enabled is False
    response = owner.patch(f"/api/clones/{clone_id}/agent", json={"public_agent_enabled": True})
    assert response.status_code == 200 and response.json()["public_agent_enabled"] is True
    db_session.expire_all()
    assert db_session.get(CloneProfile, uuid.UUID(clone_id)).public_agent_enabled is True
    # There is no public agent endpoint in this phase.
    slug = db_session.get(CloneProfile, uuid.UUID(clone_id)).slug
    for path in (f"/api/public/clones/{slug}/agent/run", f"/api/public/clones/{clone_id}/agent/run"):
        assert owner.post(path, json={"goal": "hi"}).status_code in (404, 405)


# --- Analytics ------------------------------------------------------------------------------


def test_agent_analytics(owner: TestClient, db_session: Session):
    clone_id = new_clone(owner)
    agent_id = uuid.UUID(owner.get(f"/api/clones/{clone_id}/agent").json()["id"])
    now = datetime.now(UTC).replace(tzinfo=None)
    rows = [("completed", 3, 2000), ("completed", 1, 4000), ("failed", 2, None), ("cancelled", 0, None),
            ("timeout", 4, None)]
    executions = []
    for status, steps, duration in rows:
        execution = AgentExecution(
            agent_id=agent_id, clone_id=uuid.UUID(clone_id), status=status, goal="SECRET-GOAL", total_steps=steps,
            started_at=now - timedelta(minutes=5),
            completed_at=(now - timedelta(minutes=5) + timedelta(milliseconds=duration)) if duration else None,
        )
        db_session.add(execution)
        executions.append(execution)
    old = AgentExecution(agent_id=agent_id, clone_id=uuid.UUID(clone_id), status="completed", goal="old",
                         total_steps=9, created_at=now - timedelta(days=60))
    db_session.add(old)
    db_session.flush()
    for number, (tool, status) in enumerate([("calculator", "succeeded"), ("calculator", "failed"),
                                             ("knowledge_search", "succeeded"), ("calculator", "succeeded")], 1):
        db_session.add(AgentStep(execution_id=executions[0].id, step_number=number, step_type="tool",
                                 tool_name=tool, status=status))
    db_session.add(AgentStep(execution_id=executions[0].id, step_number=9, step_type="final", status="succeeded"))
    db_session.add(AgentStep(execution_id=old.id, step_number=1, step_type="tool", tool_name="date_time",
                             status="failed"))
    db_session.commit()

    response = owner.get(f"/api/clones/{clone_id}/analytics/agent", params={"range": "7d"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["range"] == "7d"
    assert (body["executions"], body["completed"], body["failed"], body["cancelled"], body["timeout"]) == (5, 2, 1, 1, 1)
    assert body["avg_duration_ms"] == 3000
    assert body["avg_steps"] == 2.0
    assert body["tools"] == [
        {"tool": "calculator", "calls": 3, "failures": 1, "failure_rate": 0.333},
        {"tool": "knowledge_search", "calls": 1, "failures": 0, "failure_rate": 0.0},
    ]
    assert "SECRET-GOAL" not in response.text
    assert owner.get(f"/api/clones/{clone_id}/analytics/agent", params={"range": "90d"}).json()["executions"] == 6
    assert owner.get(f"/api/clones/{clone_id}/analytics/agent", params={"range": "1y"}).status_code == 400


# --- Developer API --------------------------------------------------------------------------


def test_developer_api_run_and_read(owner: TestClient, ext: TestClient, sara: TestClient, monkeypatch, llm,
                                    db_session: Session):
    clone_id = new_clone(owner)
    run_key = make_key(owner, ("agent:run",))
    read_key = make_key(owner, ("agent:read",))
    both = make_key(owner, ("agent:run", "agent:read"))
    plan(monkeypatch, llm, CALC, FINAL)
    path = f"/api/v1/clones/{clone_id}/agent/run"

    assert_api_error(api(ext, both, path, "POST", json={"goal": "What is 2 + 2?"}), 403, "permission_denied")
    enable(owner, clone_id)
    assert_api_error(api(ext, read_key, path, "POST", json={"goal": "hi"}), 403, "permission_denied")
    assert_api_error(api(ext, both, path, "POST", json={"goal": ""}), 400, "validation_error")
    response = api(ext, run_key, path, "POST", json={"goal": "What is 2 + 2?"})
    assert response.status_code == 202, response.text
    execution_id = response.json()["execution_id"]
    row = db_session.get(AgentExecution, uuid.UUID(execution_id))
    assert row.source == "api" and row.api_key_id is not None

    assert_api_error(api(ext, run_key, f"/api/v1/agent/executions/{execution_id}"), 403, "permission_denied")
    read = api(ext, read_key, f"/api/v1/agent/executions/{execution_id}")
    assert read.status_code == 200, read.text
    assert read.json()["status"] == "completed" and read.json()["final_message_id"]
    assert_api_error(api(ext, read_key, f"/api/v1/agent/executions/{uuid.uuid4()}"), 404, "resource_not_found")

    # The owner's in-app runs aren't readable through the API.
    app_run = started(owner, clone_id)
    assert_api_error(api(ext, read_key, f"/api/v1/agent/executions/{app_run['id']}"), 404, "resource_not_found")

    # Someone else's key can't run or read this clone's agent.
    sara_key = make_key(sara, ("agent:run", "agent:read"))
    assert_api_error(api(ext, sara_key, path, "POST", json={"goal": "hi"}), 404, "resource_not_found")
    assert_api_error(api(ext, sara_key, f"/api/v1/agent/executions/{execution_id}"), 404, "resource_not_found")

    # Platform switch off.
    monkeypatch.setattr(get_settings(), "agent_enabled", False)
    assert_api_error(api(ext, both, path, "POST", json={"goal": "hi"}), 403, "permission_denied")


def test_developer_scopes_listed(owner: TestClient):
    from app.developer.scopes import SCOPES

    assert "agent:run" in SCOPES and "agent:read" in SCOPES
    assert owner.post("/api/developer/keys", json={"name": "x", "scopes": ["agent:run", "agent:read"]}).status_code == 201


def test_plan_limit(owner: TestClient, ext: TestClient, monkeypatch, llm):
    from app.developer import limits

    monkeypatch.setitem(limits._DEFAULTS["free"], "agent_executions", 1)
    clone_id = new_clone(owner)
    enable(owner, clone_id)
    plan(monkeypatch, llm)
    assert run(owner, clone_id).status_code == 202
    second = run(owner, clone_id)
    assert second.status_code == 429, second.text
    key = make_key(owner, ("agent:run",))
    limited = api(ext, key, f"/api/v1/clones/{clone_id}/agent/run", "POST", json={"goal": "hi"})
    assert limited.status_code == 429 and limited.json()["error"] == "usage_limit_reached"


def test_secrets_never_in_responses(owner: TestClient, ext: TestClient, monkeypatch, llm):
    clone_id = new_clone(owner)
    enable(owner, clone_id)
    plan(monkeypatch, llm, CALC, FINAL)
    key = make_key(owner, ("agent:run", "agent:read"))
    execution = started(owner, clone_id)
    api_run = api(ext, key, f"/api/v1/clones/{clone_id}/agent/run", "POST", json={"goal": "hi"}).json()
    texts = [
        owner.get(f"/api/clones/{clone_id}/agent").text,
        owner.get(f"/api/agent/executions/{execution['id']}").text,
        owner.get(f"/api/clones/{clone_id}/agent/executions").text,
        api(ext, key, f"/api/v1/agent/executions/{api_run['execution_id']}").text,
    ]
    settings = get_settings()
    secrets = [settings.jwt_secret_key, key, "SECRET-STYLE-TEXT", "SECRET-PERSONALITY-TEXT", "key_hash",
               "password", "Traceback"]
    for text in texts:
        for secret in filter(None, secrets):
            assert secret not in text


def test_memory_proposal_decision(owner: TestClient, make_client, db_session: Session, monkeypatch, llm):
    clone_id = new_clone(owner)
    enable(owner, clone_id)
    editor = _browser(make_client, {**USER, "email": "editor@example.com", "username": "orgeditor"})
    org_with(db_session, clone_id, USER["email"], {"editor@example.com": "editor"})
    remember = {"action": "propose_memory", "summary": "Suggesting a memory",
                "memory": {"content": "I prefer tea over coffee.", "memory_type": "preference"}}
    plan(monkeypatch, llm, remember, FINAL)
    execution = started(owner, clone_id)
    proposal = execution["memory_proposal"]
    assert proposal and proposal["content"] == "I prefer tea over coffee.", execution
    base = f"/api/agent/executions/{execution['id']}/memory-proposal"
    assert owner.post(base, json={"proposal_id": "wrong", "save": True}).status_code == 409
    assert owner.post(base, json={"proposal_id": proposal["proposal_id"]}).status_code == 400  # save is required
    assert editor.post(base, json={"proposal_id": proposal["proposal_id"], "save": True}).status_code == 404
    saved = owner.post(base, json={"proposal_id": proposal["proposal_id"], "save": True})
    assert saved.status_code == 200, saved.text
    assert saved.json()["memory_proposal"] is None
    assert owner.post(base, json={"proposal_id": proposal["proposal_id"], "save": True}).status_code == 409
