#!/bin/sh
# Backend container start: optional migrations, then one uvicorn process.
#
# RUN_MIGRATIONS_ON_START=true (default) suits a single container (development).
# In production set it to false and run migrations once with the one-shot
# `migrate` service (docker-compose.prod.yml), so several starts never race.
#
# One worker on purpose: rate limits, real-time voice sessions, marketplace view
# de-duplication and the agent/avatar/webhook workers live in this process
# (see docs/SCALING_GUIDE.md).
set -eu

case "$(printf '%s' "${RUN_MIGRATIONS_ON_START:-true}" | tr '[:upper:]' '[:lower:]')" in
  1|true|yes|on)
    python -m app.db.migrate
    ;;
esac

exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --proxy-headers \
  --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}" \
  --timeout-graceful-shutdown 20
