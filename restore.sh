#!/usr/bin/env bash
set -euo pipefail

# prove a backup file restores, by restoring it into a disposable
# scratch database on the same running postgres instance. This never touches
# the live database, so it's safe to run repeatedly without risking real data.
# Usage: ./restore.sh <backup_file>

PROJECT="barq-assessment"
BACKUP_FILE="${1:?Usage: ./restore.sh <backup_file>}"
SCRATCH_DB="barq_tasks_restore_check"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
: "${POSTGRES_USER:?POSTGRES_USER not set - is .env present?}"

if [ ! -s "$BACKUP_FILE" ]; then
  echo "FAIL: backup file missing or empty: $BACKUP_FILE" >&2
  exit 1
fi

echo "Creating scratch database ${SCRATCH_DB} ..."
docker compose -p "$PROJECT" exec -T postgres \
  psql -U "$POSTGRES_USER" -d postgres \
  -c "DROP DATABASE IF EXISTS ${SCRATCH_DB};" \
  -c "CREATE DATABASE ${SCRATCH_DB};"

echo "Restoring ${BACKUP_FILE} into ${SCRATCH_DB} ..."
docker compose -p "$PROJECT" exec -T postgres \
  pg_restore -U "$POSTGRES_USER" -d "$SCRATCH_DB" < "$BACKUP_FILE"

echo "Verifying restored data ..."
COUNT=$(docker compose -p "$PROJECT" exec -T postgres \
  psql -U "$POSTGRES_USER" -d "$SCRATCH_DB" -t -c "SELECT count(*) FROM records;" | tr -d '[:space:]')

echo "Cleaning up scratch database ..."
docker compose -p "$PROJECT" exec -T postgres \
  psql -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE ${SCRATCH_DB};"

if [ -z "$COUNT" ]; then
  echo "FAIL: could not read record count from restored database" >&2
  exit 1
fi

echo "PASS: backup restored successfully, ${COUNT} record(s) present in restored copy"