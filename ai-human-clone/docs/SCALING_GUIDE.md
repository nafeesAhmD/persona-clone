# Scaling guide

**Today: run exactly one backend process.** The application is *not* horizontally scalable yet,
and nothing here claims otherwise. The backend keeps some state in its own memory; a second
process (more uvicorn workers, more containers, autoscaling) would split it. With
`ENVIRONMENT=production` the backend logs a warning when `WEB_CONCURRENCY` > 1, and the
container entrypoint starts a single uvicorn worker on purpose.

## State that lives in the backend process

| State | Where | Effect of 2+ processes | Change needed to scale out |
|---|---|---|---|
| Rate limits (chat, voice, avatar, public, login, marketplace, reports) | `app/services/rate_limit.py` (`deque` per key) | each process allows the full limit → limits multiply | shared counters (Redis `INCR`/sliding window, or a DB table) |
| Developer API rate limits | `app/developer/rate_limit.py` | same | same |
| Organization rate limits | `app/org/services/rate_limit.py` | same | same |
| Real-time voice sessions + one-time tickets | `app/realtime_voice/session_manager.py` | a WebSocket landing on another process doesn't find its session (ticket refused) | shared session store (Redis) **and** sticky routing of `/api/realtime/` WebSockets |
| Marketplace view de-duplication | `app/marketplace/service.py` (`_seen`) | a viewer counted once per process | Redis key with TTL, or check recent `AnalyticsEvent` rows |
| Agent runner | thread pool (2 workers) in `app/agent/runner.py` | runs are DB rows, but each process runs its own pool; restart recovery could mark another process's run failed | an external queue (e.g. a DB-backed job table with `SELECT … FOR UPDATE SKIP LOCKED`, or Redis/RQ/Celery) and one recovery owner |
| Avatar video jobs | thread pool (`AVATAR_VIDEO_WORKERS`) in `app/avatar/jobs.py` | same as above | same |
| Webhook delivery worker | one thread per process (`app/developer/webhooks/delivery.py`) | two workers may pick the same delivery | row locking (`SKIP LOCKED`) or a single dedicated worker |
| Expired-file cleanup | hourly task per process | harmless duplicate deletes | fine, or run once (cron) |
| Uploaded files | local volume `/app/storage` | another container on another host doesn't see the files | shared volume or object storage (S3-compatible adapter — not implemented) |

Order of work to scale out: object storage (or a shared volume) → Redis for rate limits, sessions
and view de-dup → a job table/queue with locking for agent/avatar/webhook work, run by a separate
worker container → sticky WebSockets at the proxy → then add backend replicas. Test each step.

## Vertical scaling (what works today)

* Give the backend more CPU/RAM (`BACKEND_MEM_LIMIT`); uvicorn's event loop + thread pools use them.
* `AVATAR_VIDEO_WORKERS` (default 1) for parallel videos; keep provider costs in mind.
* Move PostgreSQL / Qdrant to bigger machines or managed services (only connection settings change).
* Heavy CPU work (self-hosted voice cloning) belongs on a GPU machine (`voice-clone/colab/`) or a
  separate host; the backend talks to it over HTTP with a token.

## Database connections

Per backend process: `DB_POOL_SIZE` (default 5) + `DB_MAX_OVERFLOW` (default 10) = **15** maximum,
waiting `DB_POOL_TIMEOUT_SECONDS` (30 s) for a free one; every connection has
`statement_timeout = DB_STATEMENT_TIMEOUT_MS` (30 s) and is recycled after
`DB_POOL_RECYCLE_SECONDS` (1800 s).

Budget: `processes × (pool + overflow) + migrate (1–2) + backups/admin (≈5) < POSTGRES_MAX_CONNECTIONS (100)`.
One process uses ≤ 15 → plenty of headroom; the restricted app user is capped at 50 connections
(`deploy/postgres/init-app-user.sh`). With a managed database, check its connection limit and
use PgBouncer (transaction mode) before adding processes.

Sizing starting point: 2 vCPU / 4 GB for PostgreSQL+Qdrant+backend+frontend on one server with a
few hundred active users; PostgreSQL data grows mostly with conversations and analytics events
(`ANALYTICS_RETENTION_DAYS`, log retention settings prune them).

## Limits that protect the server (already enforced)

Uploads (`MAX_UPLOAD_SIZE_MB`, request-size middleware), audio (`MAX_AUDIO_SIZE_MB`,
`MAX_AUDIO_DURATION_SECONDS`), video (`MAX_VIDEO_DURATION_SECONDS`), chat context
(`MAX_CONVERSATION_MESSAGES`, `RAG_MAX_CONTEXT_CHARS`, `MEMORY_MAX_CONTEXT_CHARS`), agent
(`AGENT_MAX_STEPS`, `AGENT_MAX_TOOL_CALLS`, `AGENT_MAX_EXECUTION_TIME_SECONDS`), provider timeouts
(`LLM_TIMEOUT_SECONDS`, `VOICE_TIMEOUT_SECONDS`, `LIPSYNC_TIMEOUT_SECONDS`, `WEBHOOK_TIMEOUT_SECONDS`),
real-time voice (`REALTIME_VOICE_MAX_*`), pagination on list endpoints, Caddy `request_body max_size`
and container memory limits (`*_MEM_LIMIT`).
