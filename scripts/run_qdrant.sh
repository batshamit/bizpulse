#!/usr/bin/env bash
# Start Qdrant in the foreground, with project config. Run inside tmux.
set -euo pipefail

ROOT="${ROOT:-/raid/amit/mylearning/bizpulse}"
cd "$ROOT"

mkdir -p logs data/qdrant
exec ./vendor/qdrant/qdrant --config-path ./infra/qdrant/config.yaml
