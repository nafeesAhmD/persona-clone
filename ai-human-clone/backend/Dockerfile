FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=5

WORKDIR /app

COPY requirements.txt .
# The BuildKit cache keeps downloaded wheels between builds, so changing one
# requirement doesn't download everything again.
RUN --mount=type=cache,target=/root/.cache/pip env -u PIP_NO_CACHE_DIR pip install -r requirements.txt

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app


# Test image: `docker build --target test ./backend` runs the test suite.
FROM base AS test
COPY requirements-dev.txt pytest.ini ./
RUN pip install -r requirements-dev.txt
COPY tests ./tests
RUN python -m pytest


# Runtime image (default target, used by docker compose).
FROM base AS runtime

# The model cache (/app/.cache), uploaded documents (/app/storage) and generated
# speech (/app/storage/voice) are Docker volumes; create the mount points owned
# by appuser so the volumes inherit it.
RUN useradd --create-home appuser \
    && mkdir -p /app/.cache /app/storage/voice \
    && chown appuser /app/.cache /app/storage /app/storage/voice

# Migrations (unless RUN_MIGRATIONS_ON_START=false), then one uvicorn process that
# stops gracefully on SIGTERM. CRLF line endings from a Windows checkout are stripped.
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh && chmod 0755 /usr/local/bin/docker-entrypoint.sh
USER appuser

EXPOSE 8000

# Liveness only (process answers); readiness (database, Qdrant) is /api/health/ready.
# Falls back to /api/health for images built before /live existed.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request as u; exec('try: u.urlopen(\"http://127.0.0.1:8000/api/health/live\", timeout=4)\nexcept Exception: u.urlopen(\"http://127.0.0.1:8000/api/health\", timeout=4)')" || exit 1

STOPSIGNAL SIGTERM
CMD ["/usr/local/bin/docker-entrypoint.sh"]
