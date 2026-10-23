#!/bin/sh
# Back up PostgreSQL, every Qdrant collection and the uploaded files.
#
#   scripts/backup.sh                                   # development stack (docker-compose.yml)
#   COMPOSE_ARGS="-f docker-compose.prod.yml --env-file .env.production" scripts/backup.sh
#
# Writes BACKUP_DIR/<UTC timestamp>/ with:
#   postgres.dump        pg_dump custom format (restore with scripts/restore.sh)
#   qdrant/<name>.snapshot   one snapshot per collection
#   storage.tar.gz       /app/storage without the temporary speech folder
#   voices.tar.gz        self-hosted cloned voices (only if the voice-clone service runs)
#   SHA256SUMS, manifest.txt
# Then deletes backups older than BACKUP_RETENTION_DAYS (default 14).
#
# Keep BACKUP_DIR outside any web root, on a different disk/host, readable only by you.
# Run from the repository folder that holds the compose files (ai-human-clone/).
set -eu

BACKUP_DIR=${BACKUP_DIR:-./backups}
BACKUP_RETENTION_DAYS=${BACKUP_RETENTION_DAYS:-14}
COMPOSE="docker compose ${COMPOSE_ARGS:-}"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
TARGET="$BACKUP_DIR/$STAMP"

umask 077
mkdir -p "$TARGET/qdrant"
echo "Backup to $TARGET"

# --- PostgreSQL (consistent snapshot; uses the container's superuser) ----------------
$COMPOSE exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-acl' > "$TARGET/postgres.dump"
echo "  postgres.dump: $(wc -c < "$TARGET/postgres.dump") bytes"

# --- Qdrant: one snapshot per collection, via the API (the backend has URL + key) -----
SNAPSHOTS=$($COMPOSE exec -T backend python - <<'PY'
import json, os, urllib.request
base = os.environ.get("QDRANT_URL", "http://qdrant:6333").rstrip("/")
headers = {"api-key": os.environ["QDRANT_API_KEY"]} if os.environ.get("QDRANT_API_KEY") else {}
def call(method, path):
    request = urllib.request.Request(base + path, method=method, headers=headers)
    with urllib.request.urlopen(request, timeout=600) as response:
        return json.load(response)["result"]
for collection in call("GET", "/collections")["collections"]:
    snapshot = call("POST", f"/collections/{collection['name']}/snapshots?wait=true")
    print(collection["name"], snapshot["name"])
PY
)
echo "$SNAPSHOTS" | while read -r collection snapshot; do
  [ -n "$collection" ] || continue
  $COMPOSE cp "qdrant:/qdrant/snapshots/$collection/$snapshot" "$TARGET/qdrant/$collection.snapshot" </dev/null
  # The copy is ours now; don't let snapshots pile up inside the Qdrant volume.
  # (</dev/null: docker exec would otherwise eat the rest of this loop's input.)
  $COMPOSE exec -T qdrant rm -f "/qdrant/snapshots/$collection/$snapshot" "/qdrant/snapshots/$collection/$snapshot.checksum" </dev/null
  echo "  qdrant/$collection.snapshot: $(wc -c < "$TARGET/qdrant/$collection.snapshot") bytes"
done

# --- Uploaded files (temporary speech audio is left out: it expires on its own) ------
$COMPOSE exec -T backend tar -C /app -czf - --exclude=storage/voice storage > "$TARGET/storage.tar.gz"
echo "  storage.tar.gz: $(wc -c < "$TARGET/storage.tar.gz") bytes"

# --- Self-hosted cloned voices (optional service) ----------------------------------
if $COMPOSE ps --status running --services 2>/dev/null | grep -qx voice-clone; then
  $COMPOSE exec -T voice-clone tar -C /data -czf - voices > "$TARGET/voices.tar.gz"
  echo "  voices.tar.gz: $(wc -c < "$TARGET/voices.tar.gz") bytes"
fi

( cd "$TARGET" && find . -type f ! -name SHA256SUMS -exec sha256sum {} + > SHA256SUMS )
{
  echo "created_utc=$STAMP"
  echo "alembic_revision=$($COMPOSE exec -T backend alembic current 2>/dev/null | tail -n1 | cut -d' ' -f1)"
  echo "collections=$(echo "$SNAPSHOTS" | cut -d' ' -f1 | tr '\n' ' ')"
} > "$TARGET/manifest.txt"

# --- Retention ---------------------------------------------------------------------
find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name '20*Z' -mtime +"$BACKUP_RETENTION_DAYS" -exec rm -rf {} +

echo "Done: $TARGET"
