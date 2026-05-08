#!/usr/bin/env bash
# Run TEI (text-embeddings-inference) serving the configured embedding model on :8081.
# Like run_vllm.sh, requires an explicit GPU via CUDA_VISIBLE_DEVICES.

set -euo pipefail

ROOT="${ROOT:-/raid/amit/mylearning/bizpulse}"
cd "$ROOT"
. .venv/bin/activate
# shellcheck disable=SC1091
set -a; . .env; set +a

: "${CUDA_VISIBLE_DEVICES:?Refusing to start without an explicit GPU.}"

# TEI ships a binary; we don't yet — check if installed.
if ! command -v text-embeddings-router >/dev/null 2>&1; then
  echo "text-embeddings-router not installed."
  echo "Options:"
  echo "  (a) cargo install --locked --root vendor/tei text-embeddings-router (needs Rust toolchain)"
  echo "  (b) download a release binary from https://github.com/huggingface/text-embeddings-inference/releases"
  echo "  (c) run via Docker once the data-root is on /raid (deferred)"
  exit 2
fi

export HF_HOME="${HF_HOME:-$ROOT/.cache/huggingface}"
export HF_HUB_ENABLE_HF_TRANSFER=1

exec text-embeddings-router \
  --model-id "${EMBED_MODEL:-BAAI/bge-large-en-v1.5}" \
  --port 8081 \
  --hostname 127.0.0.1
