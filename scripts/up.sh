#!/usr/bin/env bash
# Open a tmux session with one window per BizPulse host service.
#
# - qdrant starts automatically (no GPU required).
# - vllm / tei-embed / tei-rerank windows are pre-loaded with the run command
#   but NOT auto-executed: you must set CUDA_VISIBLE_DEVICES yourself per
#   window before pressing Enter, since this is a shared multi-user GPU box.
# - api window starts FastAPI on :8080 once you press Enter.
#
# Attach with:    tmux attach -t bizpulse
# Stop with:      bash scripts/down.sh

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

command -v tmux >/dev/null || { echo "tmux is required."; exit 2; }

SESSION="${TMUX_SESSION:-bizpulse}"

if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "tmux session '$SESSION' already exists. Attach with: tmux attach -t $SESSION"
    echo "(or run scripts/down.sh first to recreate it)"
    exit 0
fi

mkdir -p logs

echo "creating tmux session '$SESSION'..."

# Window 0: qdrant (autostart — no GPU needed)
tmux new-session -d -s "$SESSION" -n qdrant -x 220 -y 50 \
    "bash scripts/run_qdrant.sh 2>&1 | tee -a logs/qdrant.log"

# Window 1: vllm — auto-started on dynamically allocated GPU
tmux new-window -t "$SESSION" -n vllm -c "$PWD"
tmux send-keys  -t "$SESSION:vllm" \
    "bash scripts/run_vllm.sh 2>&1 | tee -a logs/vllm.log" Enter

# Window 2: tei-embed — auto-started
tmux new-window -t "$SESSION" -n tei-embed -c "$PWD"
tmux send-keys  -t "$SESSION:tei-embed" \
    "bash scripts/run_tei_embed.sh 2>&1 | tee -a logs/tei-embed.log" Enter

# Window 3: tei-rerank — auto-started
tmux new-window -t "$SESSION" -n tei-rerank -c "$PWD"
tmux send-keys  -t "$SESSION:tei-rerank" \
    "bash scripts/run_tei_rerank.sh 2>&1 | tee -a logs/tei-rerank.log" Enter

# Window 4: FastAPI dev server (no GPU) — auto-started
tmux new-window -t "$SESSION" -n api -c "$PWD"
tmux send-keys  -t "$SESSION:api" \
    "set -a; . .env; set +a; .venv/bin/uvicorn bizpulse.api.main:app --host 127.0.0.1 --port 8080 --reload 2>&1 | tee -a logs/api.log" Enter

# Window 5: ollama (auto-started on GPU 5, 7)
tmux new-window -t "$SESSION" -n ollama -c "$PWD"
tmux send-keys  -t "$SESSION:ollama" \
    "export OLLAMA_MODELS=$PWD/.ollama/models; export CUDA_VISIBLE_DEVICES=5,7; export LD_LIBRARY_PATH=$PWD/lib/ollama/cuda_v12:\$(find \$PWD/.venv/lib/python3.11/site-packages/nvidia/ -type d -name 'lib' | tr '\\n' ':'):\$LD_LIBRARY_PATH; ./ollama serve 2>&1 | tee -a logs/ollama_serve.log" Enter

# Window 6: free shell
tmux new-window -t "$SESSION" -n shell -c "$PWD"

tmux select-window -t "$SESSION:qdrant"

cat <<EOF

session up. attach with:    tmux attach -t $SESSION

windows:
  0 qdrant     — running
  1 vllm       — fill in GPU index (e.g. CUDA_VISIBLE_DEVICES=4) then press Enter
  2 tei-embed  — fill in GPU index then press Enter
  3 tei-rerank — fill in GPU index then press Enter
  4 api        — press Enter to start FastAPI on :8080
  5 ollama     — running (local Ollama server on GPU 4)
  6 shell      — free tmux window

health check (in any window):  bash scripts/status.sh
stop everything:                bash scripts/down.sh
EOF
