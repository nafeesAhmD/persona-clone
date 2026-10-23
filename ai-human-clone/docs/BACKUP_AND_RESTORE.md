# Backup and restore

A backup counts only after a restore from it has worked. Below, **Tested** lists what was
actually restored; **Documented only** has not been exercised yet.

## What is backed up (`scripts/backup.sh`)

| Part | How | File |
|---|---|---|
| PostgreSQL (users, clones, conversations, settings, …) | `pg_dump -Fc` in the postgres container (consistent snapshot) | `postgres.dump` |
| Qdrant (knowledge + memory vectors) | snapshot API per collection, copied out, then deleted inside Qdrant | `qdrant/<collection>.snapshot` |
| Uploaded files (documents, avatars) | `tar` of `/app/storage` without the temporary `voice/` folder | `storage.tar.gz` |
| Self-hosted cloned voices | `tar` of `/data/voices`, only if the voice-clone service runs | `voices.tar.gz` |
| Integrity | `sha256sum` of every file; Alembic revision + collections | `SHA256SUMS`, `manifest.txt` |

Not included on purpose: generated speech/videos (expire within hours), the embedding model
cache (re-downloaded), logs, `.env*` (keep secrets in your password manager, separately).

## Run a backup

```bash
cd ai-human-clone
scripts/backup.sh                                            # development stack
COMPOSE_ARGS="-f docker-compose.prod.yml --env-file .env.production" \
BACKUP_DIR=/srv/backups/ai-clone BACKUP_RETENTION_DAYS=14 scripts/backup.sh   # production
```

* `BACKUP_DIR` (default `./backups`, git-ignored) must be **outside any web root**, readable only
  by the operator (the script uses `umask 077`), and copied to another machine/disk/bucket.
  Encrypt off-site copies (e.g. `restic`, `borg`, or `gpg -c`).
* `BACKUP_RETENTION_DAYS` (default 14): older timestamped folders are deleted at the end.
* Schedule daily, e.g. cron: `15 3 * * * cd /srv/app/ai-human-clone && COMPOSE_ARGS="…" BACKUP_DIR=/srv/backups/ai-clone scripts/backup.sh >> /var/log/ai-clone-backup.log 2>&1`
* Windows (Docker Desktop, Git Bash): `MSYS_NO_PATHCONV=1 sh scripts/backup.sh` — the variable stops
  Git Bash from rewriting container paths such as `/qdrant/snapshots`.

## Restore (`scripts/restore.sh`) — overwrites data

```bash
scripts/restore.sh backups/<timestamp> --yes                         # everything, into the live services
scripts/restore.sh backups/<timestamp> --yes --only postgres --target-db restore_check   # test into a scratch DB
scripts/restore.sh backups/<timestamp> --yes --only qdrant
scripts/restore.sh backups/<timestamp> --yes --only storage
```

* Checksums are verified first; a damaged backup is refused.
* PostgreSQL: `pg_restore --clean --if-exists --no-owner` (objects owned by `POSTGRES_APP_USER` when set).
* Qdrant: each snapshot is copied into the container and recovered with `snapshots/recover`
  (`priority: snapshot`), **replacing** that collection.
* Stop user traffic first (`$C stop caddy` or `frontend`), restore, then check
  `curl -fsS http://localhost:8000/api/health/ready` (inside the server) and log in.

## Tested (development stack, Windows + Docker Desktop, 2026-10-11)

1. `scripts/backup.sh` → `postgres.dump` 201,849 B, `qdrant/clone_long_term_memories.snapshot`
   684,544 B, `qdrant/clone_memories.snapshot` 712,192 B, `storage.tar.gz` 570,827 B,
   `voices.tar.gz` 627,519 B; `sha256sum -c` OK; manifest `alembic_revision=0022_marketplace`;
   no snapshot files left inside the Qdrant volume.
2. **PostgreSQL restore** into a new database `ai_clone_restore_test` (`--only postgres --target-db`):
   37 tables / 1,058 rows restored = 37 tables / 1,058 rows live — **row counts identical for every
   table**; restored `alembic_version` = `0022_marketplace`. Scratch database dropped afterwards.
3. **Qdrant restore** of `clone_memories.snapshot` into a new collection `restore_test_clone_memories`:
   13 points restored = 13 live, identical vector configuration. Test collection deleted afterwards.
   (The live collections were never recovered over.)
4. Two bugs found and fixed by these tests: `docker exec` inside the snapshot loop swallowed the
   remaining collection names (only the first collection was saved), and snapshots accumulated
   inside the Qdrant volume.

## Documented only (not yet exercised)

* Restoring **over** live data (`--yes` without `--target-db`), the storage/voices untar, and the
  production stack (`COMPOSE_ARGS=… -f docker-compose.prod.yml`) with the restricted app user.
* Off-site copy, encryption and scheduled runs.
* A full disaster-recovery drill on a new server (below).

## Disaster recovery on a new server

1. Provision the server, install Docker, clone the repository at the backed-up release
   (`manifest.txt` has the Alembic revision; check out a commit with that head).
2. Recreate `.env.production` from your password manager.
3. `$C up -d postgres qdrant` → wait until healthy.
4. `scripts/restore.sh <backup> --yes` (PostgreSQL, Qdrant, then `$C up -d backend` and
   `--only storage`, because the storage restore runs through the backend container).
5. `$C up -d` → verify health, log in, open a clone, ask a question that needs its documents.

Targets to agree on (not measured yet): **RPO** = time since the last backup (24 h with a daily
job), **RTO** ≈ 1–2 h for a single server with backups at hand.

## If Qdrant is lost but PostgreSQL is fine

Knowledge vectors can be rebuilt from the retained source documents (files and extracted text
stay in storage/PostgreSQL): call `POST /api/clones/{clone_id}/documents/{document_id}/reindex`
for each document (owner session), which re-creates the chunks and embeddings. Check the
embedding model is unchanged first (`/api/health/qdrant` shows the collection and dimensions).

**Gap:** approved long-term memories are rows in PostgreSQL, but there is no endpoint or script
to re-embed them into `clone_long_term_memories` yet — restore that collection from its Qdrant
snapshot instead (or add a rebuild command before relying on it).
