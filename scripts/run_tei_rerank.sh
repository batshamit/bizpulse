#!/usr/bin/env bash
# Run TEI as a reranker on :8082.
set -euo pipefail

ROOT="${ROOT:-/raid/amit/mylearning/bizpulse}"
cd "$ROOT"
. .venv/bin/activate
# shellcheck disable=SC1091
set -a; . .env; set +a

: "${CUDA_VISIBLE_DEVICES:?Refusing to start without an explicit GPU.}"

if ! command -v text-embeddings-router >/dev/null 2>&1; then
  echo "text-embeddings-router not installed; see scripts/run_tei_embed.sh for install options."
  exit 2
fi

export HF_HOME="${HF_HOME:-$ROOT/.cache/huggingface}"
export HF_HUB_ENABLE_HF_TRANSFER=1

exec text-embeddings-router \
  --model-id "${RERANK_MODEL:-BAAI/bge-reranker-v2-m3}" \
  --port 8082 \
  --hostname 127.0.0.1
