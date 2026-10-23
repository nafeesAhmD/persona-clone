"""Phase 15: GET /api/mobile/config is public, safe and reflects the server's features."""

from fastapi.testclient import TestClient

from app.core.config import get_settings


def test_mobile_config_is_public_and_safe(client: TestClient) -> None:
    response = client.get("/api/mobile/config")
    assert response.status_code == 200
    body = response.json()
    assert body["app_name"] == "Clone Me"
    assert body["registration_enabled"] is True and body["maintenance_mode"] is False
    assert body["voice"]["speech_to_text"] is True and body["voice"]["text_to_speech"] is True  # test fakes
    assert body["max_upload_mb"] == get_settings().max_upload_size_mb
    text = response.text.lower()
    for secret in ("key", "secret", "password", "token", "postgres", "http://", "https://"):
        assert secret not in text, secret
    assert response.headers["x-request-id"].startswith("req_")


def test_mobile_config_follows_platform_switches(client: TestClient, db_session) -> None:
    from app.services import platform_service

    row = platform_service.get_row(db_session)
    row.public_registration_enabled = False
    db_session.commit()
    platform_service.invalidate()
    assert client.get("/api/mobile/config").json()["registration_enabled"] is False


def test_mobile_config_works_during_maintenance(client: TestClient, db_session) -> None:
    from app.services import platform_service

    row = platform_service.get_row(db_session)
    row.maintenance_mode = True
    db_session.commit()
    platform_service.invalidate()
    body = client.get("/api/mobile/config").json()
    assert body["maintenance_mode"] is True and body["registration_enabled"] is False
