#!/usr/bin/env bash
# Apply all pending Postgres migrations to the bizpulse DB.
# Reads connection params from .env. Idempotent — every migration is
# IF NOT EXISTS / ADD COLUMN IF NOT EXISTS friendly.

set -euo pipefail

ROOT="${ROOT:-/raid/amit/mylearning/bizpulse}"
cd "$ROOT"

if [[ ! -f .env ]]; then
    echo "ERROR: .env missing; nothing to migrate against" >&2
    exit 2
fi

set -a; . .env; set +a

DB="${POSTGRES_DB:-bizpulse}"
USER="${POSTGRES_USER:-bizpulse}"
PASS="${POSTGRES_PASSWORD:-changeme}"
HOST="${POSTGRES_HOST:-127.0.0.1}"
PORT="${POSTGRES_PORT:-5432}"

MIG_DIR="infra/postgres/migrations"
if [[ ! -d "$MIG_DIR" ]]; then
    echo "no migrations dir at $MIG_DIR — nothing to do"
    exit 0
fi

shopt -s nullglob
files=("$MIG_DIR"/*.sql)
if [[ ${#files[@]} -eq 0 ]]; then
    echo "no .sql files in $MIG_DIR"
    exit 0
fi

for f in "${files[@]}"; do
    echo "==> applying $(basename "$f")"
    PGPASSWORD="$PASS" psql -h "$HOST" -p "$PORT" -U "$USER" -d "$DB" \
        -v ON_ERROR_STOP=1 -f "$f"
done

echo "==> done; current tenants schema:"
PGPASSWORD="$PASS" psql -h "$HOST" -p "$PORT" -U "$USER" -d "$DB" -c "\\d tenants"
