#!/usr/bin/env bash
# Install training dependencies inside virtualenv.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> Upgrading pip..."
.venv/bin/pip install -q -U pip

echo "==> Installing train dependencies group..."
.venv/bin/pip install -e ".[train]"

echo "==> Checking installation of training packages..."
.venv/bin/python -c "
import torch
import transformers
import peft
import trl
import accelerate
import deepspeed
import bitsandbytes
print('All training packages successfully imported!')
"

echo "==> Done setup_train.sh"
