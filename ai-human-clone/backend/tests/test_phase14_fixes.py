"""Phase 14 follow-ups: API conversations are separate from app chats, and the app chat
counts toward the plan's monthly chat messages."""

import pytest
from fastapi.testclient import TestClient

from tests.test_developer_keys import api, make_key

CLONE = {"name": "Ayaan AI", "owner_consent": True}


@pytest.fixture
def owner(client: TestClient, registered: dict) -> TestClient:
    return client


def test_api_lists_only_api_conversations(owner: TestClient, make_client) -> None:
    clone_id = owner.post("/api/clones", json=CLONE).json()["id"]
    app_chat = owner.post(f"/api/clones/{clone_id}/chat", json={"message": "Hello from the website"}).json()
    key = make_key(owner, scopes=("clone:chat", "conversation:read"))["key"]
    other = make_client()
    api_chat = api(other, key, f"/api/v1/clones/{clone_id}/chat", "POST", json={"message": "Hello from an app"}).json()

    listed = api(other, key, f"/api/v1/clones/{clone_id}/conversations").json()["data"]
    assert [c["id"] for c in listed] == [api_chat["conversation_id"]]
    # The owner's website chat can't be read or continued with a key.
    assert api(other, key, f"/api/v1/conversations/{app_chat['conversation_id']}").status_code == 404
    continued = api(
        other, key, f"/api/v1/clones/{clone_id}/chat", "POST",
        json={"message": "again", "conversation_id": app_chat["conversation_id"]},
    )
    assert continued.status_code == 404
    # The website still shows all of the owner's conversations.
    assert len(owner.get(f"/api/clones/{clone_id}/conversations").json()) == 2


def test_app_chat_respects_monthly_plan_limit(owner: TestClient, monkeypatch) -> None:
    from app.developer import limits

    monkeypatch.setitem(limits._DEFAULTS["free"], "chat_messages", 2)
    clone_id = owner.post("/api/clones", json=CLONE).json()["id"]
    codes = [owner.post(f"/api/clones/{clone_id}/chat", json={"message": f"hi {i}"}).status_code for i in range(3)]
    assert codes == [200, 200, 429]
    body = owner.post(f"/api/clones/{clone_id}/chat", json={"message": "hi"}).json()
    assert "detail" in body and "limit" in body["detail"].lower()
