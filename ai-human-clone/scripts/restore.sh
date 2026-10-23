#!/bin/sh
# Restore a backup made by scripts/backup.sh. Overwrites data: needs --yes.
#
#   scripts/restore.sh BACKUP_PATH --yes [--target-db NAME] [--only postgres|qdrant|storage]
#   COMPOSE_ARGS="-f docker-compose.prod.yml --env-file .env.production" scripts/restore.sh …
#
# --target-db NAME   restore PostgreSQL into another database (created if missing), e.g. to
#                    test a backup without touching the live one. Default: the live database.
# --only PART        restore just one part.
# Qdrant collections are recovered from their snapshots (replacing the live collections);
# storage.tar.gz is unpacked over /app/storage. Stop traffic (or the frontend/caddy) first.
set -eu

usage() { sed -n '2,12p' "$0"; exit 2; }
[ $# -ge 1 ] || usage
SOURCE=$1; shift
CONFIRMED=no; TARGET_DB=""; ONLY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --yes) CONFIRMED=yes ;;
    --target-db) TARGET_DB=$2; shift ;;
    --only) ONLY=$2; shift ;;
    *) usage ;;
  esac
  shift
done
[ -d "$SOURCE" ] || { echo "No backup at $SOURCE" >&2; exit 1; }
[ "$CONFIRMED" = yes ] || { echo "Refusing to restore without --yes (data will be overwritten)." >&2; exit 1; }
COMPOSE="docker compose ${COMPOSE_ARGS:-}"
wants() { [ -z "$ONLY" ] || [ "$ONLY" = "$1" ]; }

( cd "$SOURCE" && sha256sum -c --quiet SHA256SUMS ) || { echo "Checksums do not match: backup damaged" >&2; exit 1; }

if wants postgres; then
  echo "PostgreSQL -> ${TARGET_DB:-live database}"
  $COMPOSE exec -T -e TARGET_DB="$TARGET_DB" postgres sh -c '
    set -eu
    DB=${TARGET_DB:-$POSTGRES_DB}
    if [ "$(psql -U "$POSTGRES_USER" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '"'"'$DB'"'"'")" != 1 ]; then
      createdb -U "$POSTGRES_USER" "$DB"
    fi
    ROLE=""; [ -n "${POSTGRES_APP_USER:-}" ] && ROLE="--role=$POSTGRES_APP_USER"
    pg_restore -U "$POSTGRES_USER" -d "$DB" --clean --if-exists --no-owner $ROLE --exit-on-error
  ' < "$SOURCE/postgres.dump"
fi

if wants qdrant && [ -d "$SOURCE/qdrant" ]; then
  for file in "$SOURCE"/qdrant/*.snapshot; do
    [ -f "$file" ] || continue
    collection=$(basename "$file" .snapshot)
    echo "Qdrant collection $collection"
    $COMPOSE exec -T qdrant mkdir -p "/qdrant/snapshots/restore"
    $COMPOSE cp "$file" "qdrant:/qdrant/snapshots/restore/$collection.snapshot"
    $COMPOSE exec -T -e COLLECTION="$collection" backend python - <<'PY'
import json, os, urllib.request
base = os.environ.get("QDRANT_URL", "http://qdrant:6333").rstrip("/")
headers = {"Content-Type": "application/json"}
if os.environ.get("QDRANT_API_KEY"):
    headers["api-key"] = os.environ["QDRANT_API_KEY"]
name = os.environ["COLLECTION"]
body = json.dumps({"location": f"file:///qdrant/snapshots/restore/{name}.snapshot", "priority": "snapshot"}).encode()
request = urllib.request.Request(f"{base}/collections/{name}/snapshots/recover?wait=true", data=body, method="PUT", headers=headers)
with urllib.request.urlopen(request, timeout=1800) as response:
    print(" ", name, json.load(response)["status"])
PY
  done
fi

if wants storage && [ -f "$SOURCE/storage.tar.gz" ]; then
  echo "Uploaded files -> /app/storage"
  $COMPOSE exec -T backend tar -C /app -xzf - < "$SOURCE/storage.tar.gz"
fi

echo "Restore finished. Check: curl -fsS http://localhost:8000/api/health/ready"
