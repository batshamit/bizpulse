#!/usr/bin/env bash
# BizPulse demo — exercises the live FastAPI end-to-end.
#
# Usage:
#   bash scripts/demo.sh                  # against http://127.0.0.1:8080
#   API=http://localhost:8080 bash scripts/demo.sh
#
# Assumes the FastAPI server is running (e.g. via `bash scripts/up.sh` or
# directly with uvicorn). Works with either InMemoryStore or PostgresStore.

set -euo pipefail

API="${API:-http://127.0.0.1:8080}"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
dim()  { printf '\033[2m%s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m✓\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m✗\033[0m %s\n' "$*"; exit 1; }

require() {
  command -v "$1" >/dev/null 2>&1 || fail "$1 is required"
}
require curl

# --- python helper for parsing JSON without jq -----------------------------
PY_PARSE=$(cat <<'PY'
import json, sys
key = sys.argv[1]
print(json.load(sys.stdin)[key])
PY
)
parse() { python3 -c "$PY_PARSE" "$1"; }

# --- 0. Healthz ------------------------------------------------------------
bold "0) Health check"
curl -fsS "${API}/healthz" || fail "API at $API isn't responding"
echo
ok "API healthy"

# --- 1. Create a tenant ----------------------------------------------------
echo
bold "1) Create a tenant (POST /v1/tenants)"
TENANT_BODY="$(curl -fsS -X POST "${API}/v1/tenants" \
  -H 'Content-Type: application/json' \
  -d "{\"name\":\"Demo $(date +%s)\"}")"
echo "$TENANT_BODY"
API_KEY="$(echo "$TENANT_BODY" | parse api_key)"
TENANT_ID="$(echo "$TENANT_BODY" | parse id)"
ok "tenant ${TENANT_ID:0:8}… api_key ${API_KEY:0:12}…"

# --- 2. whoami sanity ------------------------------------------------------
echo
bold "2) whoami (GET /v1/tenants/me with X-API-Key)"
curl -fsS "${API}/v1/tenants/me" -H "X-API-Key: $API_KEY"
echo

# --- 3. Register a business ------------------------------------------------
echo
bold "3) Register a business (POST /v1/businesses)"
BIZ_BODY="$(curl -fsS -X POST "${API}/v1/businesses" \
  -H "X-API-Key: $API_KEY" -H 'Content-Type: application/json' \
  -d '{"url":"https://example-fintech.test","industry":"fintech"}')"
echo "$BIZ_BODY"
BIZ_ID="$(echo "$BIZ_BODY" | parse id)"
ok "business ${BIZ_ID:0:8}…"

# --- 4. Trigger analyze ----------------------------------------------------
echo
bold "4) Trigger analysis (POST /v1/businesses/{id}/analyze)"
RUN_BODY="$(curl -fsS -X POST "${API}/v1/businesses/${BIZ_ID}/analyze" \
  -H "X-API-Key: $API_KEY")"
echo "$RUN_BODY"
RUN_ID="$(echo "$RUN_BODY" | parse id)"
ok "run ${RUN_ID:0:8}… status pending"

# --- 5. List runs ----------------------------------------------------------
echo
bold "5) List runs for this business"
curl -fsS "${API}/v1/businesses/${BIZ_ID}/runs" -H "X-API-Key: $API_KEY"
echo

# --- 6. Cross-tenant isolation check ---------------------------------------
echo
bold "6) Cross-tenant isolation (a fresh tenant must NOT see this business)"
OTHER_KEY="$(curl -fsS -X POST "${API}/v1/tenants" \
  -H 'Content-Type: application/json' -d '{"name":"Other"}' | parse api_key)"
STATUS=$(curl -s -o /dev/null -w '%{http_code}' \
  "${API}/v1/businesses/${BIZ_ID}" -H "X-API-Key: $OTHER_KEY")
if [[ "$STATUS" == "404" ]]; then
  ok "cross-tenant access correctly returned 404"
else
  fail "expected 404 for cross-tenant access, got $STATUS"
fi

echo
bold "all demo steps passed"
dim "(the actual multi-agent run remains pending — waiting on a vendor key in .env)"
