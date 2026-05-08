#!/usr/bin/env bash
# Start vLLM serving the configured LLM on :8800.
# Run inside tmux. DO NOT RUN UNTIL A GPU IS RESERVED — check `nvidia-smi --query-compute-apps`
# and pick a card with low memory pressure. Set CUDA_VISIBLE_DEVICES accordingly.

set -euo pipefail

ROOT="${ROOT:-/raid/amit/mylearning/bizpulse}"
cd "$ROOT"
. .venv/bin/activate
# shellcheck disable=SC1091
set -a; . .env; set +a

: "${CUDA_VISIBLE_DEVICES:?Refusing to start without an explicit GPU. e.g. CUDA_VISIBLE_DEVICES=4 bash scripts/run_vllm.sh}"

mkdir -p logs
export HF_HOME="${HF_HOME:-$ROOT/.cache/huggingface}"
export HF_HUB_ENABLE_HF_TRANSFER=1

# vllm is OpenAI-compatible. We use port 8800 because :8000 is taken by another tenant.
exec python -m vllm.entrypoints.openai.api_server \
  --model "${LLM_MODEL:-Qwen/Qwen2.5-14B-Instruct}" \
  --host 127.0.0.1 \
  --port 8800 \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.85 \
  --enable-auto-tool-choice \
  --tool-call-parser hermes \
  --dtype float16
