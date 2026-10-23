# Operations runbook

`C` below is the compose command for the environment:

```bash
C="docker compose"                                                          # development
C="docker compose -f docker-compose.prod.yml --env-file .env.production"    # production
```

## Start / stop / status

```bash
$C up -d                       # start (production: migrate runs first, then backend)
$C ps                          # health of every service; migrate shows "exited (0)"
$C logs -f --tail 100 backend  # follow logs (JSON lines with LOG_FORMAT=json)
$C restart backend             # graceful: uvicorn finishes requests (20 s), compose waits 30 s
$C stop                        # stop everything, data stays in volumes
```
Never use `docker compose down -v` in production: `-v` deletes the volumes (database, vectors, files).

## Health

| Check | Meaning | Public? |
|---|---|---|
| `GET /api/health/live` | process answers (container healthcheck) | yes, no details |
| `GET /api/health/ready` | PostgreSQL **and** Qdrant answer → 200, else 503 with booleans | yes, booleans only |
| `GET /api/health/services`, `/api/health/qdrant`, `/api/health/llm` | more detail (collection, dimensions, provider) | yes (existing; no secrets) |
| Admin → System | errors, usage, security events | administrators |

```bash
curl -fsS http://localhost:8000/api/health/ready     # development
$C exec backend python -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8000/api/health/ready').read())"   # production (no published port)
```

## Migrations

* Production: the one-shot `migrate` service runs `python -m app.db.migrate` before the backend
  starts (backend has `RUN_MIGRATIONS_ON_START=false`), so restarts never run migrations twice.
* Procedure for a release: **backup** → `$C up -d --build` (migrate runs) → check
  `$C logs migrate` ends with the new head → `$C ps` healthy.
* Re-run by hand: `$C run --rm migrate`. Current revision: `$C run --rm migrate alembic current`.
* Development: the backend container migrates on start (`RUN_MIGRATIONS_ON_START=true`).
* A failed migration leaves the backend stopped (it depends on `migrate` succeeding): read
  `$C logs migrate`, fix, re-run. Alembic runs each migration in a transaction on PostgreSQL.

## Rollback

1. Code only (no schema change): `IMAGE_TAG=<previous tag> $C up -d`.
2. Schema changed: either `$C run --rm migrate alembic downgrade <revision>` then roll back the
   code, or — when the downgrade would drop data the new version wrote — restore the backup taken
   before the release (BACKUP_AND_RESTORE.md). Decide per release; read the migration file.

## Background work (inside the backend process)

There is no separate worker container or queue service. Started in `app/main.py` (lifespan):

| Work | How | Survives a restart? |
|---|---|---|
| Embedding model warm-up | thread at startup | re-runs |
| Initial administrator (`INITIAL_ADMIN_EMAIL`) | at startup | — |
| Avatar video jobs | thread pool (`AVATAR_VIDEO_WORKERS`, default 1); status rows in PostgreSQL | interrupted jobs are marked **failed** at startup |
| Agent runs (Phase 16) | thread pool; status rows in PostgreSQL; step/tool/time limits | interrupted runs marked failed; waiting confirmations stay |
| Webhook delivery | background thread; deliveries are rows with bounded retries (`WEBHOOK_MAX_RETRIES`), auto-disable after `WEBHOOK_AUTO_DISABLE_AFTER` failures | pending deliveries continue |
| Expired speech / video cleanup | asyncio task, hourly (`VOICE_AUDIO_RETENTION_HOURS`, `VIDEO_RETENTION_HOURS`) | restarts |
| Log retention (security/usage/error logs) | existing cleanup | — |
| Document extraction + indexing | runs in the request (thread pool), result stored on the document | re-index from the Knowledge page |

Monitor them through the admin pages (agent runs, avatar jobs, webhooks deliveries) and the logs
(`grep -E 'avatar|agent|webhook'`). Payloads, prompts and transcripts are not logged.

## Troubleshooting

| Symptom | Check / fix |
|---|---|
| Backend exits at start: "Refusing to start with ENVIRONMENT=production: …" | each item names a variable; fix `.env.production` (ENVIRONMENT_VARIABLES.md) |
| Backend unhealthy, healthcheck 400 | `ALLOWED_HOSTS` must also contain `backend,localhost,127.0.0.1` |
| `/api/health/ready` 503 `qdrant:false` | `$C ps qdrant`; `QDRANT_API_KEY` must match in Qdrant and backend |
| Chat answers "memory unavailable" | Qdrant down or collection dimension ≠ embedding model (`/api/health/qdrant`) |
| AI answers time out | provider status/quotas (Gemini "high demand" 503s happen); `LLM_TIMEOUT_SECONDS`, `GEMINI_FALLBACK_MODEL` |
| Certificate not issued | DNS must point at the server, ports 80/443 open, `$C logs caddy` |
| Microphone / real-time voice fails | needs HTTPS; WebSockets through Caddy; `REALTIME_VOICE_ENABLED=true` |
| Docker Desktop (Windows) stops answering (`docker ps` hangs, `_ping` 500) | seen several times during development under memory pressure: quit Docker Desktop, `wsl --shutdown`, start it again; data volumes survive. Give WSL enough memory (`.wslconfig`). |
| Disk filling | old images (`docker image prune`), backups retention, `json-file` logs are capped at 5×10 MB per container |
