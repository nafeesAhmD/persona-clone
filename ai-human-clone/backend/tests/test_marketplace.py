"""Phase 18: marketplace & clone discovery (docs/phase18/contract.md)."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.marketplace import service as marketplace_service
from app.models import AdminAuditLog, AnalyticsEvent, CloneProfile, CloneReport, FavoriteClone, PublicChatSession, User
from tests.conftest import USER, make_admin, open_to_public

ADMIN = {"email": "admin@example.com", "username": "admin", "full_name": "Admin", "password": "AdminPassword123!"}
SARA = {**USER, "email": "sara@example.com", "username": "sara", "full_name": "Sara"}
PRIVATE_FACT = "My salary is 90000 and my home address is 12 Secret Street Lahore."
CLONE = {
    "name": "Ayaan AI",
    "tagline": "Backend developer",
    "bio": "I write Python.",
    "profession": "Software Developer",
    "skills": ["Python", "Django"],
    "preferred_language": "English",
    "owner_consent": True,
}


@pytest.fixture(autouse=True)
def _fresh_views():
    marketplace_service.reset_view_dedupe()
    yield
    marketplace_service.reset_view_dedupe()


@pytest.fixture
def owner(client: TestClient, registered: dict) -> TestClient:
    return client


@pytest.fixture
def sara(make_client) -> TestClient:
    browser = make_client()
    assert browser.post("/api/auth/register", json=SARA).status_code == 201
    return browser


@pytest.fixture
def visitor(make_client) -> TestClient:
    return make_client()


@pytest.fixture
def admin(make_client, db_session: Session) -> TestClient:
    browser = make_client()
    assert browser.post("/api/auth/register", json=ADMIN).status_code == 201
    make_admin(db_session, ADMIN["email"])
    return browser


def new_clone(client: TestClient, **overrides) -> dict:
    response = client.post("/api/clones", json={**CLONE, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def publish(client: TestClient, clone_id: str, **settings) -> dict:
    response = client.patch(f"/api/clones/{clone_id}/marketplace", json={"enabled": True, "confirm_publish": True, **settings})
    assert response.status_code == 200, response.text
    return response.json()


def listed_clone(client: TestClient, **overrides) -> dict:
    """A public, chat-enabled clone listed in the marketplace."""
    settings = overrides.pop("marketplace", {})
    clone = new_clone(client, **overrides)
    open_to_public(client, clone["id"])
    publish(client, clone["id"], **settings)
    return clone


def slugs(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [item["slug"] for item in response.json()["items"]]


def events(db: Session, event_type: str) -> list[AnalyticsEvent]:
    return list(db.scalars(select(AnalyticsEvent).where(AnalyticsEvent.event_type == event_type)))


# --- Eligibility ----------------------------------------------------------------------------


def test_new_and_existing_clones_are_not_listed_until_the_owner_opts_in(owner: TestClient, visitor: TestClient):
    clone = new_clone(owner)
    open_to_public(owner, clone["id"])
    assert slugs(visitor.get("/api/marketplace/clones")) == []
    settings = owner.get(f"/api/clones/{clone['id']}/marketplace").json()
    assert settings["enabled"] is False and settings["eligible"] is True and settings["listed"] is False
    publish(owner, clone["id"])
    assert slugs(visitor.get("/api/marketplace/clones")) == [clone["slug"]]


def test_publishing_needs_confirmation_and_requirements(owner: TestClient, visitor: TestClient):
    clone = new_clone(owner)
    no_confirm = owner.patch(f"/api/clones/{clone['id']}/marketplace", json={"enabled": True, "short_description": "x"})
    assert no_confirm.status_code == 409 and no_confirm.json()["code"] == "confirmation_required"
    not_public = owner.patch(f"/api/clones/{clone['id']}/marketplace", json={"enabled": True, "confirm_publish": True})
    assert not_public.status_code == 409 and not_public.json()["code"] == "not_eligible"
    assert set(not_public.json()["failed"]) == {"public", "public_chat"}
    view = owner.get(f"/api/clones/{clone['id']}/marketplace").json()
    assert view["enabled"] is False and view["short_description"] is None  # nothing applied on refusal
    assert {r["key"]: r["ok"] for r in view["requirements"]}["public"] is False


@pytest.mark.parametrize("visibility", ["private", "unlisted"])
def test_private_and_unlisted_clones_are_never_listed(owner: TestClient, visitor: TestClient, visibility: str):
    clone = listed_clone(owner)
    assert owner.patch(f"/api/clones/{clone['id']}/public-settings", json={"visibility": visibility}).status_code == 200
    assert slugs(visitor.get("/api/marketplace/clones")) == []
    assert visitor.get(f"/api/marketplace/clones/{clone['slug']}").status_code == 404


@pytest.mark.parametrize(
    "change",
    [
        {"admin_disabled": True},
        {"status": "disabled"},
        {"status": "draft"},
        {"public_chat_enabled": False},
        {"marketplace_suspended": True},
    ],
)
def test_ineligible_clones_disappear(owner: TestClient, visitor: TestClient, db_session: Session, change: dict):
    clone = listed_clone(owner)
    row = db_session.get(CloneProfile, uuid.UUID(clone["id"]))
    for field, value in change.items():
        setattr(row, field, value)
    db_session.commit()
    assert slugs(visitor.get("/api/marketplace/clones")) == []
    unknown = visitor.get("/api/marketplace/clones/no-such-clone")
    hidden = visitor.get(f"/api/marketplace/clones/{clone['slug']}")
    assert hidden.status_code == unknown.status_code == 404
    assert hidden.json() == unknown.json()  # can't tell "hidden" from "doesn't exist"


def test_inactive_owner_hides_the_clone(owner: TestClient, visitor: TestClient, db_session: Session):
    clone = listed_clone(owner)
    user = db_session.scalar(select(User).where(User.email == USER["email"].lower()))
    user.is_active = False
    db_session.commit()
    assert slugs(visitor.get("/api/marketplace/clones")) == []


def test_platform_switch_off(owner: TestClient, visitor: TestClient, admin: TestClient):
    clone = listed_clone(owner)
    assert admin.patch("/api/admin/settings", json={"public_clone_discovery_enabled": False}).status_code == 200
    for path in ("/api/marketplace/clones", "/api/marketplace/clones/featured", "/api/marketplace/categories",
                 "/api/marketplace/tags", "/api/marketplace/search?q=ayaan"):
        response = visitor.get(path)
        assert response.status_code == 403 and response.json()["code"] == "discovery_off", path
    assert visitor.get(f"/api/marketplace/clones/{clone['slug']}").status_code == 200  # direct profile still works
    view = owner.get(f"/api/clones/{clone['id']}/marketplace").json()
    assert view["eligible"] is True and view["listed"] is False


def test_opt_out_keeps_visibility_and_public_page(owner: TestClient, visitor: TestClient):
    clone = listed_clone(owner)
    off = owner.patch(f"/api/clones/{clone['id']}/marketplace", json={"enabled": False})
    assert off.status_code == 200 and off.json()["enabled"] is False and off.json()["published_at"] is None
    assert slugs(visitor.get("/api/marketplace/clones")) == []
    assert visitor.get(f"/api/public/clones/{clone['slug']}").status_code == 200  # /c/{slug} unaffected
    assert owner.get(f"/api/clones/{clone['id']}").json()["visibility"] == "public"


def test_only_the_owner_manages_marketplace_settings(owner: TestClient, sara: TestClient, visitor: TestClient):
    clone = listed_clone(owner)
    assert sara.get(f"/api/clones/{clone['id']}/marketplace").status_code == 403
    assert sara.patch(f"/api/clones/{clone['id']}/marketplace", json={"enabled": False}).status_code == 403
    assert visitor.get(f"/api/clones/{clone['id']}/marketplace").status_code == 401
    private = new_clone(owner, name="Hidden")
    assert sara.get(f"/api/clones/{private['id']}/marketplace").status_code == 404


def test_owner_settings_validation(owner: TestClient):
    clone = new_clone(owner)
    url = f"/api/clones/{clone['id']}/marketplace"
    assert owner.patch(url, json={"category": "weapons"}).status_code == 400
    assert owner.patch(url, json={"tags": ["ok", "x"]}).status_code == 400  # too short
    assert owner.patch(url, json={"tags": [f"tag{i}" for i in range(9)]}).status_code == 400
    assert owner.patch(url, json={"tags": ["<script>"]}).status_code == 400
    assert owner.patch(url, json={"short_description": "x" * 201}).status_code == 400
    assert owner.patch(url, json={"featured_rank": 1}).status_code == 400  # admin only
    ok = owner.patch(url, json={"category": "technology", "tags": [" Python ", "python", "Web Dev"], "short_description": " Hi\x00 "})
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["tags"] == ["python", "web dev"] and body["short_description"] == "Hi" and body["category"] == "technology"
    assert body["preview"]["category"] == {"slug": "technology", "name": "Technology & Programming"}


# --- Public responses --------------------------------------------------------------------


def test_public_responses_hold_public_metadata_only(owner: TestClient, visitor: TestClient, db_session: Session):
    clone = listed_clone(owner, marketplace={"category": "technology", "tags": ["python"], "short_description": "I build APIs"})
    row = db_session.get(CloneProfile, uuid.UUID(clone["id"]))
    row.marketplace_suspended_reason = "internal note"
    row.personality_description = "SECRET PERSONALITY"
    db_session.commit()
    owner.post(f"/api/clones/{clone['id']}/knowledge", json={"title": "Private", "content": PRIVATE_FACT})
    listing = visitor.get("/api/marketplace/clones")
    profile = visitor.get(f"/api/marketplace/clones/{clone['slug']}")
    assert profile.status_code == 200
    for response in (listing, profile, visitor.get("/api/marketplace/search?q=python")):
        text = response.text.lower()
        for secret in (USER["email"].lower(), "internal note", "secret personality", "90000", "owner_id", "suspended"):
            assert secret not in text, secret
    body = profile.json()
    assert body["public_url"] == f"/c/{clone['slug']}" and body["tags"] == ["python"]
    assert body["capabilities"] == {"chat": True, "voice": False, "avatar": False, "realtime_voice": False}
    assert body["is_favorite"] is False and body["favorites"] == 0


def test_search_fields_and_filters(owner: TestClient, visitor: TestClient):
    a = listed_clone(owner, name="Ayaan AI", profession="Software Developer", skills=["Django"],
                     marketplace={"category": "technology", "tags": ["python", "web dev"], "short_description": "Backend APIs"})
    b = listed_clone(owner, name="Zara Chef", profession="Chef", skills=["Baking"], tagline="Home cooking",
                     marketplace={"category": "lifestyle", "tags": ["cooking"], "short_description": "Recipes from Lahore"})
    get = lambda **params: slugs(visitor.get("/api/marketplace/clones", params=params))  # noqa: E731
    assert set(get()) == {a["slug"], b["slug"]}
    assert get(q="ayaan") == [a["slug"]]  # name
    assert get(q="recipes") == [b["slug"]]  # short description
    assert get(q="django") == [a["slug"]]  # skills
    assert get(q="cooking") == [b["slug"]]  # tag / tagline
    assert get(q="lifestyle") == [b["slug"]]  # category
    assert get(category="technology") == [a["slug"]]
    assert get(tags="web dev") == [a["slug"]]
    assert get(tags="python,cooking") == []  # all tags must match
    assert get(profession="chef") == [b["slug"]]
    assert get(voice_enabled="true") == [] and set(get(voice_enabled="false")) == {a["slug"], b["slug"]}
    assert get(avatar_enabled="true") == []
    assert slugs(visitor.get("/api/marketplace/search", params={"q": "lahore"})) == [b["slug"]]


def test_voice_filter_follows_public_voice(owner: TestClient, visitor: TestClient):
    voiced = listed_clone(owner, name="Voiced")
    listed_clone(owner, name="Silent")
    assert owner.patch(f"/api/clones/{voiced['id']}/voice/settings", json={"voice_consent_given": True, "voice_enabled": True}).status_code == 200
    open_to_public(owner, voiced["id"], voice=True)
    assert slugs(visitor.get("/api/marketplace/clones", params={"voice_enabled": "true"})) == [voiced["slug"]]
    card = next(i for i in visitor.get("/api/marketplace/clones").json()["items"] if i["slug"] == voiced["slug"])
    assert card["capabilities"]["voice"] is True


@pytest.mark.parametrize("q", ["%", "_", "100%", "a_b", "' OR 1=1 --", '"; DROP TABLE clone_profiles; --', "\\"])
def test_search_is_safe_with_wildcards_and_quotes(owner: TestClient, visitor: TestClient, q: str):
    listed_clone(owner, name="Ayaan AI")
    response = visitor.get("/api/marketplace/clones", params={"q": q})
    assert response.status_code == 200 and response.json()["items"] == []  # literal text, not a pattern or SQL
    assert visitor.get("/api/marketplace/clones").json()["total"] == 1  # table intact


def test_pagination_and_validation(owner: TestClient, visitor: TestClient):
    for i in range(5):
        listed_clone(owner, name=f"Clone {i}")
    first = visitor.get("/api/marketplace/clones", params={"page_size": 2}).json()
    second = visitor.get("/api/marketplace/clones", params={"page_size": 2, "page": 2}).json()
    last = visitor.get("/api/marketplace/clones", params={"page_size": 2, "page": 3}).json()
    beyond = visitor.get("/api/marketplace/clones", params={"page_size": 2, "page": 9}).json()
    assert first["total"] == 5 and len(first["items"]) == 2 and len(last["items"]) == 1 and beyond["items"] == []
    assert not {i["slug"] for i in first["items"]} & {i["slug"] for i in second["items"]}
    for params in ({"page_size": 49}, {"page_size": 0}, {"page": 0}, {"sort": "rating"}, {"category": "x"},
                   {"q": "x" * 101}, {"tags": "a,b,c,d,e,f"}, {"tags": "<b>"}):
        assert visitor.get("/api/marketplace/clones", params=params).status_code == 400, params
    assert visitor.get("/api/marketplace/search").status_code == 400
    assert visitor.get("/api/marketplace/search", params={"q": "   "}).status_code == 400


def test_sorting(owner: TestClient, sara: TestClient, visitor: TestClient, db_session: Session):
    old = listed_clone(owner, name="Old One")
    new = listed_clone(owner, name="New One")
    fav = listed_clone(owner, name="Liked One")
    now = datetime.now(UTC)
    for clone, age in ((old, 3), (new, 1), (fav, 2)):
        db_session.get(CloneProfile, uuid.UUID(clone["id"])).published_at = now - timedelta(days=age)
    db_session.commit()
    assert slugs(visitor.get("/api/marketplace/clones")) == [new["slug"], fav["slug"], old["slug"]]  # newest default
    assert sara.post(f"/api/marketplace/favorites/{fav['id']}").status_code == 201
    db_session.add(PublicChatSession(clone_id=uuid.UUID(old["id"]), session_token_hash="a" * 64, expires_at=now + timedelta(days=1)))
    db_session.add(PublicChatSession(clone_id=uuid.UUID(old["id"]), session_token_hash="b" * 64, expires_at=now + timedelta(days=1)))
    db_session.commit()
    # popular = favorites + distinct public chat sessions (30 days): old 2, liked 1, new 0
    assert slugs(visitor.get("/api/marketplace/clones", params={"sort": "popular"})) == [old["slug"], fav["slug"], new["slug"]]
    relevance = visitor.get("/api/marketplace/clones", params={"q": "one"}).json()
    assert relevance["sort"] == "relevance" and relevance["total"] == 3


def test_featured_categories_and_tags(owner: TestClient, visitor: TestClient, admin: TestClient):
    a = listed_clone(owner, name="A", marketplace={"category": "technology", "tags": ["python", "ai"]})
    b = listed_clone(owner, name="B", marketplace={"category": "technology", "tags": ["python"]})
    hidden = new_clone(owner, name="Hidden")  # not listed: never counted
    owner.patch(f"/api/clones/{hidden['id']}/marketplace", json={"category": "technology", "tags": ["python"]})
    assert visitor.get("/api/marketplace/clones/featured").json() == []
    assert admin.patch(f"/api/admin/marketplace/clones/{b['id']}/visibility", json={"featured_rank": 1}).status_code == 200
    assert admin.patch(f"/api/admin/marketplace/clones/{a['id']}/visibility", json={"featured_rank": 2}).status_code == 200
    assert [c["slug"] for c in visitor.get("/api/marketplace/clones/featured").json()] == [b["slug"], a["slug"]]
    assert admin.patch(f"/api/admin/marketplace/clones/{a['id']}/visibility", json={"featured_rank": None}).status_code == 200
    assert [c["slug"] for c in visitor.get("/api/marketplace/clones/featured").json()] == [b["slug"]]
    counts = {c["slug"]: c["count"] for c in visitor.get("/api/marketplace/categories").json()}
    assert counts["technology"] == 2 and counts["other"] == 0 and len(counts) == 10
    assert visitor.get("/api/marketplace/tags").json() == [{"tag": "python", "count": 2}, {"tag": "ai", "count": 1}]


# --- Favorites -----------------------------------------------------------------------------


def test_favorites(owner: TestClient, sara: TestClient, visitor: TestClient, db_session: Session):
    clone = listed_clone(owner)
    assert visitor.post(f"/api/marketplace/favorites/{clone['id']}").status_code == 401
    assert visitor.get("/api/marketplace/favorites").status_code == 401
    first = sara.post(f"/api/marketplace/favorites/{clone['id']}")
    again = sara.post(f"/api/marketplace/favorites/{clone['id']}")
    assert first.status_code == 201 and again.status_code == 200
    assert db_session.scalar(select(FavoriteClone).where(FavoriteClone.clone_id == uuid.UUID(clone["id"]))) is not None
    assert len(list(db_session.scalars(select(FavoriteClone)))) == 1
    assert sara.get(f"/api/marketplace/clones/{clone['slug']}").json()["is_favorite"] is True
    assert visitor.get(f"/api/marketplace/clones/{clone['slug']}").json()["favorites"] == 1
    assert slugs(sara.get("/api/marketplace/favorites")) == [clone["slug"]]
    assert slugs(owner.get("/api/marketplace/favorites")) == []  # per user
    # Hidden while not listed, back when listed again (the row is kept).
    owner.patch(f"/api/clones/{clone['id']}/marketplace", json={"enabled": False})
    assert slugs(sara.get("/api/marketplace/favorites")) == []
    publish(owner, clone["id"])
    assert slugs(sara.get("/api/marketplace/favorites")) == [clone["slug"]]
    assert sara.delete(f"/api/marketplace/favorites/{clone['id']}").status_code == 204
    assert sara.delete(f"/api/marketplace/favorites/{clone['id']}").status_code == 204  # idempotent
    assert slugs(sara.get("/api/marketplace/favorites")) == []
    assert len(events(db_session, "marketplace_clone_favorited")) == 1
    assert len(events(db_session, "marketplace_clone_unfavorited")) == 1


def test_only_listed_clones_can_be_saved(owner: TestClient, sara: TestClient):
    private = new_clone(owner)
    unlisted = new_clone(owner, name="Unlisted")
    open_to_public(owner, unlisted["id"], visibility="unlisted")
    for clone_id in (private["id"], unlisted["id"], str(uuid.uuid4())):
        response = sara.post(f"/api/marketplace/favorites/{clone_id}")
        assert response.status_code == 404 and response.json()["code"] == "not_found"


def test_favorites_are_unique_in_the_database(owner: TestClient, sara: TestClient, db_session: Session):
    clone = listed_clone(owner)
    sara.post(f"/api/marketplace/favorites/{clone['id']}")
    user = db_session.scalar(select(User).where(User.email == SARA["email"]))
    db_session.add(FavoriteClone(user_id=user.id, clone_id=uuid.UUID(clone["id"])))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


# --- Reports and moderation ----------------------------------------------------------------


def test_reports_anonymous_and_logged_in(owner: TestClient, sara: TestClient, visitor: TestClient, db_session: Session):
    clone = listed_clone(owner)
    url = f"/api/marketplace/clones/{clone['slug']}/report"
    anon = visitor.post(url, json={"reason": "impersonation", "description": "  Not really him \x07 "})
    assert anon.status_code == 201 and anon.json()["status"] == "open"
    assert visitor.post(url, json={"reason": "spam"}).json()["id"] == anon.json()["id"]  # one open report each
    assert visitor.post(url, json={"reason": "spam"}).status_code == 200
    mine = sara.post(url, json={"reason": "privacy"})
    assert mine.status_code == 201 and mine.json()["id"] != anon.json()["id"]
    rows = list(db_session.scalars(select(CloneReport).order_by(CloneReport.created_at)))
    assert len(rows) == 2
    assert rows[0].reporter_user_id is None and len(rows[0].reporter_key) == 64  # a hash, not the address
    assert rows[0].description == "Not really him"
    reported = events(db_session, "marketplace_clone_reported")
    assert len(reported) == 2 and all("Not really" not in json.dumps(e.metadata) for e in reported)


def test_report_validation_and_unknown_clones(owner: TestClient, visitor: TestClient):
    clone = listed_clone(owner)
    url = f"/api/marketplace/clones/{clone['slug']}/report"
    assert visitor.post(url, json={"reason": "boring"}).status_code == 400
    assert visitor.post(url, json={"reason": "spam", "description": "x" * 1001}).status_code == 400
    assert visitor.post(url, json={"reason": "spam", "extra": 1}).status_code == 400
    private = new_clone(owner, name="Private")
    assert visitor.post(f"/api/marketplace/clones/{private['slug']}/report", json={"reason": "spam"}).status_code == 404
    assert visitor.post("/api/marketplace/clones/nobody/report", json={"reason": "spam"}).status_code == 404


def test_reports_are_rate_limited(owner: TestClient, visitor: TestClient, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "marketplace_reports_per_hour", 2)
    clones = [listed_clone(owner, name=f"Clone {i}") for i in range(3)]
    codes = [visitor.post(f"/api/marketplace/clones/{c['slug']}/report", json={"reason": "spam"}).status_code for c in clones]
    assert codes == [201, 201, 429]


def test_admin_moderation(owner: TestClient, sara: TestClient, admin: TestClient, visitor: TestClient, db_session: Session):
    clone = listed_clone(owner)
    report_id = sara.post(f"/api/marketplace/clones/{clone['slug']}/report", json={"reason": "spam", "description": "ads"}).json()["id"]
    visitor.post(f"/api/marketplace/clones/{clone['slug']}/report", json={"reason": "other"})
    for path in ("/api/admin/marketplace/reports",):
        assert sara.get(path).status_code == 403 and visitor.get(path).status_code == 401
    assert sara.patch(f"/api/admin/marketplace/reports/{report_id}", json={"status": "resolved"}).status_code == 403
    assert sara.patch(f"/api/admin/marketplace/clones/{clone['id']}/visibility", json={"suspended": True}).status_code == 403

    listing = admin.get("/api/admin/marketplace/reports").json()
    assert listing["total"] == 2 and {r["reporter"] for r in listing["items"]} == {SARA["email"], "anonymous"}
    done = admin.patch(f"/api/admin/marketplace/reports/{report_id}", json={"status": "resolved", "resolution_note": "warned"})
    assert done.status_code == 200 and done.json()["status"] == "resolved" and done.json()["reviewed_at"]
    assert admin.get("/api/admin/marketplace/reports", params={"status": "open"}).json()["total"] == 1
    assert admin.patch(f"/api/admin/marketplace/reports/{uuid.uuid4()}", json={"status": "resolved"}).status_code == 404

    suspended = admin.patch(f"/api/admin/marketplace/clones/{clone['id']}/visibility", json={"suspended": True, "reason": "spam ads"})
    assert suspended.status_code == 200 and suspended.json()["suspended"] is True
    assert slugs(visitor.get("/api/marketplace/clones")) == []
    owner_view = owner.get(f"/api/clones/{clone['id']}/marketplace").json()
    assert owner_view["suspended"] is True and "spam ads" not in json.dumps(owner_view)
    assert visitor.get(f"/api/public/clones/{clone['slug']}").status_code == 200  # the clone itself stays
    assert admin.patch(f"/api/admin/marketplace/clones/{clone['id']}/visibility", json={"suspended": False}).status_code == 200
    assert slugs(visitor.get("/api/marketplace/clones")) == [clone["slug"]]
    actions = [row.action for row in db_session.scalars(select(AdminAuditLog).order_by(AdminAuditLog.created_at))]
    assert actions[-3:] == ["marketplace.report_updated", "marketplace.clone_suspended", "marketplace.clone_unsuspended"]


def test_resolution_notes_never_reach_the_public(owner: TestClient, sara: TestClient, admin: TestClient, visitor: TestClient):
    clone = listed_clone(owner)
    report_id = sara.post(f"/api/marketplace/clones/{clone['slug']}/report", json={"reason": "spam"}).json()["id"]
    admin.patch(f"/api/admin/marketplace/reports/{report_id}", json={"status": "dismissed", "resolution_note": "MODNOTE"})
    for response in (visitor.get(f"/api/marketplace/clones/{clone['slug']}"), visitor.get("/api/marketplace/clones"),
                     owner.get(f"/api/clones/{clone['id']}/marketplace")):
        assert "MODNOTE" not in response.text


# --- Analytics ----------------------------------------------------------------------------


def test_views_are_deduplicated_and_counted(owner: TestClient, sara: TestClient, visitor: TestClient, db_session: Session):
    clone = listed_clone(owner)
    for _ in range(3):
        assert visitor.get(f"/api/marketplace/clones/{clone['slug']}").status_code == 200
    sara.get(f"/api/marketplace/clones/{clone['slug']}")
    visitor.get("/api/marketplace/clones/nobody")  # a failed view is not counted
    views = events(db_session, "marketplace_clone_viewed")
    assert len(views) == 2 and all(str(e.clone_id) == clone["id"] for e in views)
    sara.post(f"/api/marketplace/favorites/{clone['id']}")
    db_session.add(PublicChatSession(clone_id=uuid.UUID(clone["id"]), session_token_hash="c" * 64,
                                     expires_at=datetime.now(UTC) + timedelta(days=1)))
    db_session.commit()
    stats = owner.get(f"/api/clones/{clone['id']}/marketplace/analytics", params={"days": 7}).json()
    assert stats["views"] == 2 and stats["favorites"] == 1 and stats["public_chat_starts"] == 1
    assert len(stats["daily"]) == 7 and stats["daily"][-1]["views"] == 2 and stats["daily"][-1]["favorites"] == 1
    assert sara.get(f"/api/clones/{clone['id']}/marketplace/analytics").status_code == 403
    assert owner.get(f"/api/clones/{clone['id']}/marketplace/analytics", params={"days": 91}).status_code == 400


def test_search_and_category_events_hold_no_query_text(owner: TestClient, visitor: TestClient, db_session: Session):
    listed_clone(owner, marketplace={"category": "technology"})
    visitor.get("/api/marketplace/search", params={"q": "secret words"})
    visitor.get("/api/marketplace/clones", params={"category": "technology"})
    visitor.get("/api/marketplace/clones", params={"page_size": 99})  # rejected: no event
    searches = events(db_session, "marketplace_search_performed")
    assert len(searches) == 1 and "secret" not in json.dumps(searches[0].metadata)
    assert searches[0].metadata["q_length"] == len("secret words") and searches[0].metadata["endpoint"] == "search"
    categories = events(db_session, "marketplace_category_viewed")
    assert len(categories) == 1 and categories[0].metadata["category"] == "technology"


# --- Regression ---------------------------------------------------------------------------


def test_existing_public_discovery_and_profile_still_work(owner: TestClient, visitor: TestClient):
    clone = new_clone(owner)
    open_to_public(owner, clone["id"])
    # The old discovery list keeps listing public chat clones without a marketplace opt-in.
    listed = visitor.get("/api/public/clones").json()
    assert [item["slug"] for item in listed["items"]] == [clone["slug"]]
    profile = visitor.get(f"/api/public/clones/{clone['slug']}")
    assert profile.status_code == 200 and profile.json()["name"] == CLONE["name"]
    assert visitor.post(f"/api/public/clones/{clone['slug']}/chat", json={"message": "Hi"}).status_code == 200


def test_admin_clone_list_and_partial_updates(owner: TestClient, sara: TestClient, admin: TestClient, visitor: TestClient):
    listed = listed_clone(owner, name="Listed One")
    other = listed_clone(owner, name="Other One")
    new_clone(owner, name="Never Opted In")
    sara.post(f"/api/marketplace/clones/{listed['slug']}/report", json={"reason": "spam"})
    assert sara.get("/api/admin/marketplace/clones").status_code == 403
    all_rows = admin.get("/api/admin/marketplace/clones").json()
    assert all_rows["total"] == 2 and {r["slug"] for r in all_rows["items"]} == {listed["slug"], other["slug"]}
    row = next(r for r in all_rows["items"] if r["slug"] == listed["slug"])
    assert row["listed"] is True and row["open_reports"] == 1 and row["suspended"] is False

    url = f"/api/admin/marketplace/clones/{listed['id']}/visibility"
    assert admin.patch(url, json={}).status_code == 400  # nothing to change
    assert admin.patch(url, json={"suspended": True, "reason": "spam"}).json()["suspended"] is True
    featured = admin.patch(url, json={"featured_rank": 3}).json()
    assert featured["suspended"] is True and featured["featured_rank"] == 3  # a rank never lifts a suspension
    assert admin.patch(url, json={"reason": "spam ads"}).json()["suspended_reason"] == "spam ads"
    cleared = admin.patch(url, json={"featured_rank": None}).json()
    assert cleared["featured_rank"] is None and cleared["suspended"] is True
    assert admin.get("/api/admin/marketplace/clones", params={"status": "featured"}).json()["total"] == 0
    suspended = admin.get("/api/admin/marketplace/clones", params={"status": "suspended"}).json()
    assert [r["slug"] for r in suspended["items"]] == [listed["slug"]] and suspended["items"][0]["listed"] is False
    assert [r["slug"] for r in admin.get("/api/admin/marketplace/clones", params={"status": "listed"}).json()["items"]] == [other["slug"]]
    assert admin.get("/api/admin/marketplace/clones", params={"q": "other"}).json()["total"] == 1
    assert admin.get("/api/admin/marketplace/clones", params={"status": "bogus"}).status_code == 400
    assert visitor.get(f"/api/marketplace/clones/{other['slug']}").json()["id"] == other["id"]
