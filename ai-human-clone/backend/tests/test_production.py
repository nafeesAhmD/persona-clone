"""Phase 19: production settings checks, health probes, docs/hosts gating, logging, pool and migration lock."""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.logging_setup import JsonFormatter, RequestIdFilter, request_id_var
from app.core.production import ProductionConfigError, production_problems, validate_production
from app.db import migrate
from app.db.session import engine_options

BACKEND_DIR = Path(__file__).resolve().parents[1]
SECRET = "k" * 48
GOOD = {
    "environment": "production",
    "jwt_secret_key": SECRET,
    "cookie_secure": True,
    "cors_origins": ["https://clones.example.com"],
    "frontend_url": "https://clones.example.com",
    "database_url": "postgresql+psycopg://ahc_app:a-long-db-password@db:5432/ai_clone",
    "qdrant_api_key": "q" * 40,
}


def settings(**overrides) -> Settings:
    return Settings(_env_file=None, **{**GOOD, **overrides})


# --- Startup checks ----------------------------------------------------------------


def test_a_safe_production_setup_passes():
    assert production_problems(settings()) == []
    validate_production(settings())  # no exception


@pytest.mark.parametrize(
    ("overrides", "name"),
    [
        ({"jwt_secret_key": None}, "JWT_SECRET_KEY"),
        ({"jwt_secret_key": "short"}, "JWT_SECRET_KEY"),
        ({"jwt_secret_key": "test-secret-key-that-is-long-enough-for-hs256"}, "JWT_SECRET_KEY"),
        ({"cookie_secure": False}, "COOKIE_SECURE"),
        ({"cors_origins": []}, "CORS_ORIGINS"),
        ({"cors_origins": ["*"]}, "CORS_ORIGINS"),
        ({"cors_origins": ["http://clones.example.com"]}, "CORS_ORIGINS"),
        ({"cors_origins": ["https://localhost:3007"]}, "CORS_ORIGINS"),
        ({"frontend_url": "http://localhost:3007"}, "FRONTEND_URL"),
        ({"public_site_url": "http://clones.example.com"}, "PUBLIC_SITE_URL"),
        ({"public_api_url": "https://127.0.0.1:8000"}, "PUBLIC_API_URL"),
        ({"database_url": "postgresql+psycopg://clone:clone@db:5432/ai_clone"}, "DATABASE_URL"),
        ({"qdrant_api_key": None}, "QDRANT_API_KEY"),
        ({"api_docs_enabled": True}, "API_DOCS_ENABLED"),
        ({"realtime_voice_audio_retention_enabled": True}, "REALTIME_VOICE_AUDIO_RETENTION_ENABLED"),
    ],
)
def test_each_unsafe_setting_is_refused_by_name_only(overrides, name):
    unsafe = settings(**overrides)
    problems = production_problems(unsafe)
    assert any(problem.startswith(name + ":") for problem in problems), problems
    with pytest.raises(ProductionConfigError) as refused:
        validate_production(unsafe)
    message = str(refused.value)
    assert name in message
    for value in overrides.values():  # the values themselves are never echoed
        if isinstance(value, str) and len(value) > 8:
            assert value not in message


def test_development_is_not_checked():
    validate_production(settings(environment="development", jwt_secret_key=None, cookie_secure=False, qdrant_api_key=None))


def test_docs_default_off_in_production_on_in_development():
    assert settings().docs_enabled is False
    assert settings(environment="development").docs_enabled is True
    assert settings(api_docs_enabled=False, environment="development").docs_enabled is False


def test_many_processes_only_warn(monkeypatch, caplog):
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    with caplog.at_level(logging.WARNING, logger="app.core.production"):
        validate_production(settings())
    assert "single backend process" in caplog.text


def _run_app_script(script: str, **env: str) -> subprocess.CompletedProcess:
    """Import the app in a fresh interpreter with the given environment."""
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("JWT_", "COOKIE_", "CORS_", "ENVIRONMENT"))}
    clean.update(env)
    return subprocess.run(
        [sys.executable, "-c", script], cwd=BACKEND_DIR, env=clean, capture_output=True, text=True, timeout=120
    )


PRODUCTION_ENV = {
    "ENVIRONMENT": "production",
    "JWT_SECRET_KEY": SECRET,
    "COOKIE_SECURE": "true",
    "CORS_ORIGINS": "https://clones.example.com",
    "FRONTEND_URL": "https://clones.example.com",
    "DATABASE_URL": GOOD["database_url"],
    "QDRANT_API_KEY": "q" * 40,
}


def test_production_app_refuses_unsafe_settings_without_values():
    result = _run_app_script("import app.main", **{**PRODUCTION_ENV, "COOKIE_SECURE": "false", "QDRANT_API_KEY": ""})
    assert result.returncode != 0
    assert "COOKIE_SECURE" in result.stderr and "QDRANT_API_KEY" in result.stderr
    assert SECRET not in result.stderr


def test_production_app_hides_docs_and_checks_hosts():
    script = """
from fastapi.testclient import TestClient
from app.main import app
client = TestClient(app, base_url="https://api.example.com")
print(client.get("/openapi.json").status_code, client.get("/docs").status_code)
print(client.get("/").status_code)
print(client.get("/", headers={"host": "evil.example"}).status_code)
print(client.get("/api/v1/openapi.json").status_code)
print(client.get("/api/health/live", headers={"host": "172.18.0.5:8000"}).status_code)
print(client.get("/api/health/ready", headers={"host": "172.18.0.5:8000"}).status_code)
print(client.get("/", headers={"host": "127.0.0.1:8000"}).status_code)
"""
    result = _run_app_script(script, **PRODUCTION_ENV, ALLOWED_HOSTS="api.example.com")
    assert result.returncode == 0, result.stderr[-2000:]
    lines = result.stdout.split()
    assert lines[:2] == ["404", "404"]  # app docs off
    assert lines[2] == "200"  # allowed host
    assert lines[3] == "400"  # Host header not in ALLOWED_HOSTS
    assert lines[4] == "200"  # the developer API reference stays public by design
    assert lines[5] == "200"  # probes by container IP are exempt from the host check
    assert lines[6] in ("200", "503")  # (no database here) but never 400
    assert lines[7] == "200"  # the container itself


# --- Health probes -------------------------------------------------------------------


def test_live_needs_nothing(client: TestClient, monkeypatch):
    monkeypatch.setattr("app.api.routes.health.check_database", lambda: False)
    response = client.get("/api/health/live")
    assert response.status_code == 200 and response.json() == {"status": "alive"}


def test_ready_reports_booleans_only(client: TestClient, monkeypatch, qdrant):
    monkeypatch.setattr("app.api.routes.health.check_database", lambda: True)  # tests use SQLite
    ok = client.get("/api/health/ready")
    assert ok.status_code == 200 and ok.json() == {"status": "ready", "checks": {"database": True, "qdrant": True}}

    monkeypatch.setattr("app.api.routes.health.check_database", lambda: False)
    monkeypatch.setattr(qdrant, "health_check", lambda: False)
    down = client.get("/api/health/ready")
    assert down.status_code == 503
    assert down.json() == {"status": "not_ready", "checks": {"database": False, "qdrant": False}}


def test_existing_health_endpoints_still_work(client: TestClient):
    assert client.get("/api/health").json() == {"status": "healthy"}
    assert client.get("/api/health/services").status_code == 200


# --- Logging -----------------------------------------------------------------------------


def _record(message: str, **extra) -> logging.LogRecord:
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, message, None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_lines_carry_the_request_id():
    token = request_id_var.set("req_0123456789abcdef01234567")
    try:
        record = _record("hello %s" % "world", route="/api/clones/{clone_id}", status=200, duration_ms=1.5)
        RequestIdFilter().filter(record)
        line = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(token)
    assert line["message"] == "hello world" and line["level"] == "INFO" and line["logger"] == "app.test"
    assert line["request_id"] == "req_0123456789abcdef01234567"
    assert line["route"] == "/api/clones/{clone_id}" and line["status"] == 200 and line["duration_ms"] == 1.5


def test_requests_are_logged_with_route_template_not_query(client: TestClient, registered, caplog):
    import uuid

    clone_id = str(uuid.uuid4())
    with caplog.at_level(logging.INFO, logger="app.access"):
        status = client.get(f"/api/clones/{clone_id}?secret=value").status_code
    lines = [r for r in caplog.records if r.name == "app.access"]
    assert lines, "no access log line"
    assert lines[-1].route == "/api/clones/{clone_id}" and lines[-1].status == status
    message = lines[-1].getMessage()  # (the test client's own httpx log line has the URL)
    assert "secret" not in message and clone_id not in message


def test_health_probes_are_not_access_logged(client: TestClient, caplog):
    with caplog.at_level(logging.INFO, logger="app.access"):
        client.get("/api/health/live")
    assert not [r for r in caplog.records if r.name == "app.access"]


# --- Database --------------------------------------------------------------------------


def test_postgres_pool_and_statement_timeout():
    options = engine_options(settings(db_pool_size=7, db_max_overflow=3, db_pool_timeout_seconds=12, db_statement_timeout_ms=5000))
    assert options["pool_size"] == 7 and options["max_overflow"] == 3 and options["pool_timeout"] == 12
    assert options["pool_pre_ping"] is True
    assert options["connect_args"]["options"] == "-c statement_timeout=5000"
    assert "options" not in engine_options(settings(db_statement_timeout_ms=0))["connect_args"]


def test_sqlite_keeps_default_pool():
    assert engine_options(settings(database_url="sqlite://")) == {"pool_pre_ping": True}


class _FakeConnection:
    def __init__(self, dialect: str) -> None:
        self.dialect = type("D", (), {"name": dialect})()
        self.sql: list[str] = []

    def execute(self, statement, params=None):
        self.sql.append(str(statement))


def test_migration_lock_on_postgres_only():
    pg = _FakeConnection("postgresql")
    with migrate.migration_lock(pg):
        assert pg.sql == ["SELECT pg_advisory_lock(:key)"]
    assert pg.sql[-1] == "SELECT pg_advisory_unlock(:key)"

    released = _FakeConnection("postgresql")
    with pytest.raises(RuntimeError), migrate.migration_lock(released):
        raise RuntimeError("upgrade failed")
    assert released.sql[-1] == "SELECT pg_advisory_unlock(:key)"  # released even on failure

    lite = _FakeConnection("sqlite")
    with migrate.migration_lock(lite):
        pass
    assert lite.sql == []


def test_migrations_can_be_skipped_at_start():
    result = _run_app_script("import runpy; runpy.run_module('app.db.migrate', run_name='__main__')", RUN_MIGRATIONS_ON_START="false")
    assert result.returncode == 0, result.stderr[-1000:]
    assert "skipping migrations" in result.stderr


# --- Shutdown ---------------------------------------------------------------------------


def test_job_pools_shut_down_cleanly():
    from app.agent import runner
    from app.avatar import jobs
    from app.services import monitoring

    for module in (runner, jobs):
        module.shutdown()  # nothing started: no error
        module._executor()
        module.shutdown()
        assert module._executor.cache_info().currsize == 0
    assert monitoring.flush(0.1) is True
