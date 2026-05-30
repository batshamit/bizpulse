#!/usr/bin/env bash
# ============================================================
# BizPulse — Launch GGUF LLM Servers using compiled llama-server
# ============================================================

set -e

# Paths to GGUF model blobs
LLAMA_70B="/raid/amit/mylearning/bizpulse/.ollama/models/blobs/sha256-4824460d29f2058aaf6e1118a63a7a197a09bed509f0e7d4e2efb1ee273b447d"
GEMMA_27B="/raid/amit/mylearning/bizpulse/.ollama/models/blobs/sha256-d7e4b00a7d7a8d03d4eed9b0f3f61a427e9f0fc5dea6aeb414e41dee23dc8ecc"
GRANITE_8B="/raid/amit/mylearning/bizpulse/.ollama/models/blobs/sha256-59c55d0e7b6a16d103f324fe4d2cc83843936e1ac65e93b632b6dc577d732630"

SERVER_BIN="./llama.cpp/build/bin/llama-server"

echo "============================================================"
echo "🚀 Starting GPU-Accelerated GGUF LLM Servers..."
echo "============================================================"

# Port 8801: Llama-3.3-70B on GPUs 5,6,7 (sharded)
echo "📍 Launching Llama-3.3-70B GGUF on Port 8801 (GPUs: 5, 6, 7)..."
tmux send-keys -t bizpulse:8 "CUDA_VISIBLE_DEVICES=5,6,7 $SERVER_BIN -m $LLAMA_70B --port 8801 --gpu-layers 99 --host 127.0.0.1 --ctx-size 32768 --parallel 1 --threads 4 2>&1 | tee logs/llama_70b_server.log" Enter

# Port 8802: Gemma-2-27B on GPU 3
echo "📍 Launching Gemma-2-27B GGUF on Port 8802 (GPU: 3)..."
# Create a new tmux window or use window 9 if it exists
if tmux list-windows -t bizpulse | grep -q "9: "; then
    tmux send-keys -t bizpulse:9 "CUDA_VISIBLE_DEVICES=3 $SERVER_BIN -m $GEMMA_27B --port 8802 --gpu-layers 99 --host 127.0.0.1 --ctx-size 32768 --parallel 1 --threads 4 2>&1 | tee logs/gemma_27b_server.log" Enter
else
    tmux new-window -t bizpulse -n gemma-27b-gguf -c "$PWD"
    tmux send-keys -t bizpulse:gemma-27b-gguf "CUDA_VISIBLE_DEVICES=3 $SERVER_BIN -m $GEMMA_27B --port 8802 --gpu-layers 99 --host 127.0.0.1 --ctx-size 32768 --parallel 1 --threads 4 2>&1 | tee logs/gemma_27b_server.log" Enter
fi

# Port 8803: Granite-3.2-8B on GPU 7
echo "📍 Launching Granite-3.2-8B GGUF on Port 8803 (GPU: 7)..."
# Check if granite-8b window already exists
if tmux list-windows -t bizpulse | grep -q "granite-8b"; then
    tmux send-keys -t bizpulse:granite-8b "CUDA_VISIBLE_DEVICES=7 $SERVER_BIN -m $GRANITE_8B --port 8803 --gpu-layers 99 --host 127.0.0.1 --ctx-size 32768 --parallel 1 --threads 4 2>&1 | tee logs/granite_8b_server.log" Enter
else
    tmux new-window -t bizpulse -n granite-8b -c "$PWD"
    tmux send-keys -t bizpulse:granite-8b "CUDA_VISIBLE_DEVICES=7 $SERVER_BIN -m $GRANITE_8B --port 8803 --gpu-layers 99 --host 127.0.0.1 --ctx-size 32768 --parallel 1 --threads 4 2>&1 | tee logs/granite_8b_server.log" Enter
fi

echo "============================================================"
echo "✨ GGUF LLM servers initiated inside tmux session 'bizpulse'!"
echo "   - Llama 70B   -> Port 8801 (Window 8)"
echo "   - Gemma 27B   -> Port 8802 (Window 9)"
echo "   - Granite 8B  -> Port 8803 (Window granite-8b)"
echo "============================================================"
