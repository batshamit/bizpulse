#!/usr/bin/env bash
# Create the `bizpulse` role + DB on the existing local Postgres at :5432
# and apply infra/postgres/init.sql. Idempotent.
#
# Requires: ability to run psql as the postgres superuser.
# On Ubuntu we can normally use `sudo -u postgres psql` (interactive sudo).
# If sudo isn't available, set PGSUPERUSER + PGSUPERPASSWORD and we'll connect normally.

set -euo pipefail

ROOT="${ROOT:-/raid/amit/mylearning/bizpulse}"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "ERROR: .env missing — copy .env.example to .env and edit it."
  exit 2
fi

# shellcheck disable=SC1091
set -a; . .env; set +a

DB="${POSTGRES_DB:-bizpulse}"
USER="${POSTGRES_USER:-bizpulse}"
PASS="${POSTGRES_PASSWORD:-changeme}"
HOST="${POSTGRES_HOST:-127.0.0.1}"
PORT="${POSTGRES_PORT:-5432}"

run_super() {
  if [[ -n "${PGSUPERUSER:-}" && -n "${PGSUPERPASSWORD:-}" ]]; then
    PGPASSWORD="$PGSUPERPASSWORD" psql -h "$HOST" -p "$PORT" -U "$PGSUPERUSER" -v ON_ERROR_STOP=1 "$@"
  else
    # Use the Unix socket (no -h) so we get peer auth as the postgres OS
    # user — no password needed. cd /tmp avoids the harmless
    # "could not change directory" warning when sudo switches user.
    (cd /tmp && sudo -u postgres psql -v ON_ERROR_STOP=1 "$@")
  fi
}

echo "==> create role $USER (idempotent)"
run_super -c "DO \$\$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$USER') THEN
    CREATE ROLE \"$USER\" WITH LOGIN PASSWORD '$PASS';
  END IF;
END \$\$;"

echo "==> create db $DB owned by $USER (idempotent)"
EXISTS="$(run_super -tA -c "SELECT 1 FROM pg_database WHERE datname='$DB';")"
if [[ "$EXISTS" != "1" ]]; then
  run_super -c "CREATE DATABASE \"$DB\" OWNER \"$USER\";"
else
  echo "    already exists"
fi

echo "==> ensure extensions in $DB (as superuser)"
# Extensions need superuser to install. We do them once here, then init.sql
# becomes IF-NOT-EXISTS no-ops when applied as the bizpulse user.
# Keep this list in sync with infra/postgres/init.sql.
run_super -d "$DB" -c "
    CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";
    CREATE EXTENSION IF NOT EXISTS \"pgcrypto\";
    CREATE EXTENSION IF NOT EXISTS \"citext\";
"

echo "==> grant schema usage to $USER on $DB"
# bizpulse role owns the DB but on some setups it doesn't own the public schema;
# this makes the user-level apply step succeed regardless.
run_super -d "$DB" -c "GRANT ALL ON SCHEMA public TO \"$USER\";"

echo "==> apply infra/postgres/init.sql"
PGPASSWORD="$PASS" psql -h "$HOST" -p "$PORT" -U "$USER" -d "$DB" -v ON_ERROR_STOP=1 -f infra/postgres/init.sql

echo "==> smoke test"
PGPASSWORD="$PASS" psql -h "$HOST" -p "$PORT" -U "$USER" -d "$DB" -c "\\dt"
