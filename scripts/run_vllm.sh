#!/usr/bin/env bash
# Start vLLM serving the configured LLM on :8800.
# Run inside tmux. DO NOT RUN UNTIL A GPU IS RESERVED — check `nvidia-smi --query-compute-apps`
# and pick a card with low memory pressure. Set CUDA_VISIBLE_DEVICES accordingly.

set -euo pipefail

ROOT="${ROOT:-/raid/amit/mylearning/bizpulse}"
cd "$ROOT"
# Path-based virtualenv activation
export PATH="$ROOT/.venv/bin:$PATH"

# Load environment
set -a; . .env; set +a

# Query dynamic allocation
echo "Allocating GPUs dynamically..."
ALLOCATION=$(python3 scripts/gpu_allocator.py --service vllm)
eval "$ALLOCATION"

echo "Using vLLM with $ALLOCATION"
export CUDA_VISIBLE_DEVICES
export TENSOR_PARALLEL_SIZE

mkdir -p logs
export HF_HOME="${HF_HOME:-$ROOT/.cache/huggingface}"
export HF_HUB_ENABLE_HF_TRANSFER=1

VLLM_MODEL="Qwen/Qwen2.5-14B-Instruct"
if [[ "${LLM_MODEL:-}" != *":"* && -n "${LLM_MODEL:-}" ]]; then
  VLLM_MODEL="$LLM_MODEL"
fi

# vllm is OpenAI-compatible. We use port 8800 because :8000 is taken by another tenant.
exec python3 scripts/run_vllm_patched.py \
  --model "$VLLM_MODEL" \
  --host 127.0.0.1 \
  --port 8800 \
  --max-model-len 16384 \
  --gpu-memory-utilization "0.7" \
  --enable-auto-tool-choice \
  --tool-call-parser hermes \
  --dtype float16 \
  --tensor-parallel-size "$TENSOR_PARALLEL_SIZE"
