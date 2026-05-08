#!/usr/bin/env bash
# Stop the BizPulse host-mode tmux session.
# Data under data/ and logs/ is preserved; only running processes are killed.
set -euo pipefail

SESSION="${TMUX_SESSION:-bizpulse}"

if ! tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "no tmux session '$SESSION' to stop"
    exit 0
fi

echo "killing tmux session '$SESSION' (services receive SIGHUP)"
tmux kill-session -t "$SESSION"
echo "done. data preserved under data/ and logs/"
