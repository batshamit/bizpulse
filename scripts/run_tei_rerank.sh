#!/usr/bin/env bash
# Run TEI as a reranker on :8082.
set -euo pipefail

ROOT="${ROOT:-/raid/amit/mylearning/bizpulse}"
cd "$ROOT"
# Path-based virtualenv activation
export PATH="$ROOT/.venv/bin:$PATH"

# Load environment
set -a; . .env; set +a

# Query dynamic allocation
echo "Allocating GPU dynamically..."
ALLOCATION=$(python3 scripts/gpu_allocator.py --service rerank)
eval "$ALLOCATION"

echo "Using Reranking server with $ALLOCATION"
export CUDA_VISIBLE_DEVICES

export HF_HOME="${HF_HOME:-$ROOT/.cache/huggingface}"
export HF_HUB_ENABLE_HF_TRANSFER=1

# Start the Python TEI server replica for reranking
exec python3 scripts/tei_server.py \
  --task rerank \
  --port 8082 \
  --model-id "${RERANK_MODEL:-BAAI/bge-reranker-v2-m3}" \
  --host 127.0.0.1
