#!/usr/bin/env bash
# Run TEI (text-embeddings-inference) serving the configured embedding model on :8081.
# Like run_vllm.sh, requires an explicit GPU via CUDA_VISIBLE_DEVICES.

set -euo pipefail

ROOT="${ROOT:-/raid/amit/mylearning/bizpulse}"
cd "$ROOT"
# Path-based virtualenv activation
export PATH="$ROOT/.venv/bin:$PATH"

# Load environment
set -a; . .env; set +a

# Query dynamic allocation
echo "Allocating GPU dynamically..."
ALLOCATION=$(python3 scripts/gpu_allocator.py --service embed)
eval "$ALLOCATION"

echo "Using Embedding server with $ALLOCATION"
export CUDA_VISIBLE_DEVICES

export HF_HOME="${HF_HOME:-$ROOT/.cache/huggingface}"
export HF_HUB_ENABLE_HF_TRANSFER=1

# Start the Python TEI server replica
exec python3 scripts/tei_server.py \
  --task embed \
  --port 8081 \
  --model-id "${EMBED_MODEL:-BAAI/bge-large-en-v1.5}" \
  --host 127.0.0.1
