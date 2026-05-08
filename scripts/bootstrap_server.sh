#!/usr/bin/env bash
# Idempotent first-run setup for /raid/amit/mylearning/bizpulse on the dev server.
# Safe to re-run.

set -euo pipefail

ROOT="${ROOT:-/raid/amit/mylearning/bizpulse}"
QDRANT_VERSION="${QDRANT_VERSION:-v1.12.4}"

cd "$ROOT"

echo "==> [1/5] Ensure venv"
if [[ ! -d .venv ]]; then
  /usr/local/bin/python3.10 -m venv .venv
fi
. .venv/bin/activate
python -m pip install -q -U pip wheel setuptools

echo "==> [2/5] Install project deps (editable)"
pip install -q -e ".[dev]"

echo "==> [3/5] Install Qdrant binary at vendor/qdrant if missing"
mkdir -p vendor logs data/qdrant
if [[ ! -x vendor/qdrant/qdrant ]]; then
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  echo "    downloading qdrant ${QDRANT_VERSION}..."
  curl -fsSL "https://github.com/qdrant/qdrant/releases/download/${QDRANT_VERSION}/qdrant-x86_64-unknown-linux-gnu.tar.gz" \
    | tar -xz -C "$TMP"
  mkdir -p vendor/qdrant
  mv "$TMP/qdrant" vendor/qdrant/qdrant
  chmod +x vendor/qdrant/qdrant
fi
echo "    qdrant binary: $(./vendor/qdrant/qdrant --version 2>&1 | head -1)"

echo "==> [4/5] Postgres DB + role"
bash scripts/init_postgres.sh || echo "    (init_postgres reported errors — review above)"

echo "==> [5/5] Smoke test Python import"
python -c "import bizpulse; print(f'bizpulse {bizpulse.__version__} OK')"

echo
echo "Bootstrap complete. Next:"
echo "  bash scripts/run_qdrant.sh &        # start Qdrant on :6333"
echo "  uvicorn bizpulse.api.main:app --port 8080 --host 127.0.0.1"
echo "  bash scripts/status.sh              # sanity check"
