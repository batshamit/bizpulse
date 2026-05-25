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

# Window 1: vllm — pre-typed, user picks GPU and presses Enter
tmux new-window -t "$SESSION" -n vllm -c "$PWD"
tmux send-keys  -t "$SESSION:vllm" \
    "# Pick a GPU first:  nvidia-smi --query-gpu=index,memory.free --format=csv" Enter
tmux send-keys  -t "$SESSION:vllm" \
    "CUDA_VISIBLE_DEVICES= bash scripts/run_vllm.sh 2>&1 | tee -a logs/vllm.log"

# Window 2: tei-embed
tmux new-window -t "$SESSION" -n tei-embed -c "$PWD"
tmux send-keys  -t "$SESSION:tei-embed" \
    "CUDA_VISIBLE_DEVICES= bash scripts/run_tei_embed.sh 2>&1 | tee -a logs/tei-embed.log"

# Window 3: tei-rerank
tmux new-window -t "$SESSION" -n tei-rerank -c "$PWD"
tmux send-keys  -t "$SESSION:tei-rerank" \
    "CUDA_VISIBLE_DEVICES= bash scripts/run_tei_rerank.sh 2>&1 | tee -a logs/tei-rerank.log"

# Window 4: FastAPI dev server (no GPU)
tmux new-window -t "$SESSION" -n api -c "$PWD"
tmux send-keys  -t "$SESSION:api" \
    "set -a; . .env; set +a; .venv/bin/uvicorn bizpulse.api.main:app --host 127.0.0.1 --port 8080 --reload 2>&1 | tee -a logs/api.log"

# Window 5: free shell
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
  5 shell      — free tmux window

health check (in any window):  bash scripts/status.sh
stop everything:                bash scripts/down.sh
EOF
