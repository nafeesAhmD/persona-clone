"""Startup checks for ENVIRONMENT=production.

The backend refuses to start in production with a development or unsafe setting
(an empty or placeholder JWT secret, insecure cookies, localhost origins, the
default database password, an open Qdrant, ...). Problems name the variable and the
reason, never its value. Development is not affected.
"""

import logging
import os
from urllib.parse import urlsplit

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.core.config import Settings

logger = logging.getLogger(__name__)

MIN_SECRET_LENGTH = 32
# Values people copy from examples. Compared case-insensitively.
PLACEHOLDER_SECRETS = {
    "change-me",
    "changeme",
    "change-this",
    "secret",
    "your-secret",
    "your-secret-key",
    "your_secret_key",
    "replace-me",
    "dev-secret",
    "development",
    "test-secret-key-that-is-long-enough-for-hs256",
}
DEFAULT_DATABASE_CREDENTIALS = ("clone", "clone")
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "::1")


class ProductionConfigError(RuntimeError):
    """Raised at startup when production settings are unsafe."""


def _is_local(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host in _LOCAL_HOSTS or host.endswith(".localhost")


def _https(url: str | None) -> bool:
    return bool(url) and urlsplit(url).scheme == "https" and not _is_local(url)


def _default_database_credentials(database_url: str) -> bool:
    try:
        url = make_url(database_url)
    except ArgumentError:
        return False
    return (url.username, url.password) == DEFAULT_DATABASE_CREDENTIALS


def production_problems(settings: Settings) -> list[str]:
    """Every unsafe production setting as "NAME: reason" (values are never included)."""
    problems: list[str] = []
    secret = settings.jwt_secret_key or ""
    if not secret:
        problems.append("JWT_SECRET_KEY: not set")
    elif len(secret) < MIN_SECRET_LENGTH:
        problems.append(f"JWT_SECRET_KEY: shorter than {MIN_SECRET_LENGTH} characters")
    elif secret.strip().lower() in PLACEHOLDER_SECRETS:
        problems.append("JWT_SECRET_KEY: an example placeholder")
    if not settings.cookie_secure:
        problems.append("COOKIE_SECURE: must be true (cookies only over HTTPS)")
    origins = [origin for origin in settings.cors_origins if origin]
    if not origins:
        problems.append("CORS_ORIGINS: empty (set the site's https origin)")
    for origin in origins:
        if origin.strip() == "*":
            problems.append("CORS_ORIGINS: must not contain *")
        elif not _https(origin):
            problems.append("CORS_ORIGINS: every origin must be https and not localhost")
            break
    if not _https(settings.frontend_url):
        problems.append("FRONTEND_URL: must be an https URL that is not localhost")
    for name, value in (("PUBLIC_SITE_URL", settings.public_site_url), ("PUBLIC_API_URL", settings.public_api_url)):
        if value and not _https(value):
            problems.append(f"{name}: must be an https URL that is not localhost")
    if _default_database_credentials(settings.database_url):
        problems.append("DATABASE_URL: uses the default development user/password")
    if not settings.qdrant_api_key:
        problems.append("QDRANT_API_KEY: not set (Qdrant would accept anyone on its network)")
    if settings.api_docs_enabled:
        problems.append("API_DOCS_ENABLED: must be false or unset in production")
    if settings.realtime_voice_audio_retention_enabled:
        problems.append("REALTIME_VOICE_AUDIO_RETENTION_ENABLED: must be false (not implemented)")
    return list(dict.fromkeys(problems))


def validate_production(settings: Settings) -> None:
    """Raise ProductionConfigError listing the problems; no-op outside production."""
    if not settings.is_production:
        return
    problems = production_problems(settings)
    if problems:
        raise ProductionConfigError(
            "Refusing to start with ENVIRONMENT=production: " + "; ".join(problems)
        )
    warn_multiple_processes()


def warn_multiple_processes() -> None:
    """Some state lives in the backend process (see docs/SCALING_GUIDE.md): more than one
    process would split it. Warn, but don't refuse: the operator may know better."""
    try:
        workers = int(os.environ.get("WEB_CONCURRENCY", "1") or 1)
    except ValueError:
        workers = 1
    if workers > 1:
        logger.warning(
            "WEB_CONCURRENCY=%d: rate limits, real-time voice sessions, marketplace view "
            "de-duplication and the background job runners are kept per process. Run a single "
            "backend process (or add a shared store) or these limits will not hold.",
            workers,
        )
