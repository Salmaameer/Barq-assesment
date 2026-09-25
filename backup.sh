#!/usr/bin/env bash
set -euo pipefail

# dump the running PostgreSQL database to a file on the host.


PROJECT="barq-assessment"
OUT_DIR="${1:-backups}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_FILE="${OUT_DIR}/barq_tasks_${TIMESTAMP}.dump"

# Load .env so we know the real user/db name without hardcoding secrets here.
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi
: "${POSTGRES_USER:?POSTGRES_USER not set - is .env present?}"
: "${POSTGRES_DB:?POSTGRES_DB not set - is .env present?}"

mkdir -p "$OUT_DIR"

# Fail fast with a clear message if postgres isn't even running, rather than
# letting pg_dump produce a confusing connection error.
if ! docker compose -p "$PROJECT" ps postgres --status running >/dev/null 2>&1; then
  echo "FAIL: postgres container is not running" >&2
  exit 1
fi

echo "Backing up ${POSTGRES_DB} to ${OUT_FILE} ..."


docker compose -p "$PROJECT" exec -T postgres \
  pg_dump -U "$POSTGRES_USER" -Fc -d "$POSTGRES_DB" > "$OUT_FILE"

SIZE=$(wc -c < "$OUT_FILE")
if [ "$SIZE" -eq 0 ]; then
  echo "FAIL: backup file is empty" >&2
  rm -f "$OUT_FILE"
  exit 1
fi

echo "PASS: backup written (${SIZE} bytes) -> ${OUT_FILE}"
