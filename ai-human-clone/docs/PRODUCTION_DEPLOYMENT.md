# Production deployment

**Status:** the project has **not** been deployed publicly. No hosting provider is configured
in the repository, so this is a provider-independent **Docker + Caddy** path for one Linux
server (VPS or dedicated). It was validated locally (compose config, migrations, backups —
see "What was verified"), not on a real domain.

## Architecture

```
Users ──HTTPS──► Caddy (80/443, automatic Let's Encrypt)
                   ├── /api/*  (incl. WebSockets) ──► backend  (FastAPI, 1 process)
                   └── everything else           ──► frontend (Next.js standalone)
backend ──► PostgreSQL (restricted app user)   backend ──► Qdrant (API key)
backend ──► AI/voice/avatar providers (HTTPS)  backend ──► voice-clone (optional profile)
```

* Only Caddy publishes ports. PostgreSQL, Qdrant, backend and frontend live on the private
  `internal` Docker network.
* Background work (avatar videos, agent runs, webhook delivery, cleanup) runs **inside the
  backend process** — there is no separate worker container yet. See OPERATIONS_RUNBOOK.md.
* One backend process (see SCALING_GUIDE.md). No Kubernetes.

## Server requirements

* Linux x86-64 with Docker Engine ≥ 24 and the Compose plugin.
* RAM: ~4 GB without voice cloning (backend ~1.5–3 GB with the local embedding model,
  PostgreSQL + Qdrant ~1 GB, frontend ~200 MB); +4–6 GB for the optional CPU voice-clone service.
* Disk: 20 GB+ (images, model cache ~0.5 GB, data, backups elsewhere).
* A domain whose DNS `A`/`AAAA` record points at the server; ports 80 and 443 open.

## First deployment

```bash
git clone <your repository> && cd <repo>/ai-human-clone
cp .env.production.example .env.production
chmod 600 .env.production
# Edit .env.production: DOMAIN, ACME_EMAIL, PUBLIC_API_URL, FRONTEND_URL, CORS_ORIGINS,
# ALLOWED_HOSTS (your domain plus backend,localhost,127.0.0.1), PUBLIC_SITE_URL
# (all https://your-domain), and generate every secret:
openssl rand -base64 48 | tr -d '\n/+=' | cut -c1-48     # JWT_SECRET_KEY, passwords, QDRANT_API_KEY
# Add at least one LLM key (GEMINI_API_KEY or ANTHROPIC_API_KEY).

docker compose -f docker-compose.prod.yml --env-file .env.production config --quiet   # validate
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

What happens: PostgreSQL starts and (first time only) creates the restricted app user →
Qdrant starts with its API key → `migrate` runs Alembic once and exits → backend starts
(it refuses to start if a production setting is unsafe, listing each problem) → frontend →
Caddy obtains the certificate.

Optional voice cloning: add `--profile voice-clone` and set `VOICE_CLONE_SERVICE_TOKEN`,
`LOCAL_VOICE_CLONE_URL=http://voice-clone:8100`.

## Verify

```bash
C="docker compose -f docker-compose.prod.yml --env-file .env.production"
$C ps                                                   # all healthy; migrate "exited (0)"
$C logs migrate | tail -n 5                             # "...upgrade ... -> <head>"
curl -fsS https://YOUR_DOMAIN/api/health/live           # {"status":"alive"...}
curl -fsS https://YOUR_DOMAIN/api/health/ready          # 200 when database + Qdrant are ready
curl -sI https://YOUR_DOMAIN | grep -i strict-transport  # HSTS from Caddy
```

Then log in, make the first administrator (`INITIAL_ADMIN_EMAIL` = an existing account's
email, restart backend), upload a document and chat with a clone.

## Updates and rollback

```bash
git pull
scripts/backup.sh   # with COMPOSE_ARGS, see BACKUP_AND_RESTORE.md — always before migrating
IMAGE_TAG=$(git rev-parse --short HEAD) $C up -d --build      # migrate runs again, then backend
```

Rollback of code: `IMAGE_TAG=<previous tag> $C up -d` (images are kept by tag).
Rollback of the database: migrations have downgrades (`$C run --rm migrate alembic downgrade -1`),
but a downgrade can drop columns/tables added by the release — prefer restoring the backup taken
just before the update when data shapes changed. See OPERATIONS_RUNBOOK.md.

## HTTPS, cookies, CORS

* Caddy terminates TLS and adds HSTS; the frontend sends its own security headers
  (`next.config.ts`), the backend adds API security headers and checks `ALLOWED_HOSTS`.
* `COOKIE_SECURE=true` (enforced), `COOKIE_SAMESITE=lax` (frontend and API on one domain).
* `CORS_ORIGINS` = the exact site origin. If the API lives on another subdomain, set
  `PUBLIC_API_URL` to it, add a second Caddy site block, and keep cookies working with
  `COOKIE_SAMESITE=lax` only when both are under the same registrable domain.
* Real-time voice needs HTTPS (browsers only allow the microphone on secure origins);
  Caddy proxies its WebSockets as they are (`/api/realtime/...`).

## Storage

Uploaded documents, avatars and generated audio/video are files in the `document_storage` /
`voice_audio` volumes (`/app/storage`), private — served only through authorised API routes.
Temporary audio/video expire after `VOICE_AUDIO_RETENTION_HOURS` / `VIDEO_RETENTION_HOURS`
(hourly cleanup in the backend). There is **no object-storage (S3) adapter yet**; to move to
one, the file storage module (`app/services/file_storage.py`, `app/voice/storage.py`,
`app/avatar/storage.py`) would need an adapter, then copy the volume contents to the bucket.
Until then, back up the volumes (BACKUP_AND_RESTORE.md).

## For a specific host

* **Plain VPS** (any provider): exactly the steps above.
* **Managed PostgreSQL**: drop the `postgres` service, point `DATABASE_URL` (in `.env.production`,
  and remove it from `x-backend-env`) at the managed instance with TLS (`?sslmode=require`).
* **Managed Qdrant (Qdrant Cloud)**: drop the `qdrant` service, set `QDRANT_URL` + `QDRANT_API_KEY`.
* **PaaS without Docker Compose** (Render, Fly.io, Railway, …): build the three Dockerfiles as
  separate services, run `python -m app.db.migrate` as a release/pre-deploy command with
  `RUN_MIGRATIONS_ON_START=true` only there, keep exactly one backend instance, and give the
  backend a persistent disk for `/app/storage` (or add object storage first).
  Not tested on any of these.

## What was verified (local, Windows + Docker Desktop, 2026-10-11)

* `docker compose config` (dev) and `docker compose -f docker-compose.prod.yml config` with the
  placeholder env file: valid; only Caddy publishes ports.
* Migrations from an empty PostgreSQL database to head, `downgrade -1`, `upgrade head`: OK.
* Backup and restore of PostgreSQL and Qdrant (see BACKUP_AND_RESTORE.md).
* Not verified: a real domain/certificate, the restricted-user init script on a fresh volume,
  the production stack running end to end.
