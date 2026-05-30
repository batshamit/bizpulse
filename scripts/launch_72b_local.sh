#!/usr/bin/env bash
# ============================================================
# BizPulse — Launch script for Qwen 2.5 72B AWQ local server
# ============================================================

set -e

# Configure HuggingFace cache and transfer acceleration
export HF_HOME=/raid/amit/mylearning/bizpulse/.cache/huggingface
export HF_HUB_ENABLE_HF_TRANSFER=1

# Exclude busy GPUs and target idle ones (3, 5, 6, 7)
export CUDA_VISIBLE_DEVICES=3,5,6,7

echo "============================================================"
echo "🚀 Starting Qwen 2.5 72B AWQ download and server setup..."
echo "📍 GPUs Selected: 3, 5, 6, 7 (Free VRAM ~104 GB)"
echo "📍 Target Port: 8801"
echo "============================================================"

# Execute vLLM server from the virtual environment
exec /raid/amit/mylearning/bizpulse/.venv/bin/python3 -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen2.5-72B-Instruct-GPTQ-Int4 \
    --quantization gptq \
    --port 8801 \
    --tensor-parallel-size 4 \
    --gpu-memory-utilization 0.75 \
    --max-model-len 32768 \
    --trust-remote-code \
    --dtype float16
