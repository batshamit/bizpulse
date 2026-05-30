#!/usr/bin/env bash
# Wrapper to launch model fine-tuning across multiple GPUs using DeepSpeed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Default configurations
MODEL_ID="Qwen/Qwen2.5-Coder-14B-Instruct"
CONTEXT_LENGTH=4096
EPOCHS=3
DATASET_PATH="data/train.json"
GPUS="0,1" # Default to GPUs 0 and 1
DEEFSPEED_STAGE=2
QLORA=true

# Parse parameters
while [[ $# -gt 0 ]]; do
  case $1 in
    --model_id)
      MODEL_ID="$2"
      shift 2
      ;;
    --context_length)
      CONTEXT_LENGTH="$2"
      shift 2
      ;;
    --epochs)
      EPOCHS="$2"
      shift 2
      ;;
    --dataset_path)
      DATASET_PATH="$2"
      shift 2
      ;;
    --gpus)
      GPUS="$2"
      shift 2
      ;;
    --deepspeed_stage)
      DEEFSPEED_STAGE="$2"
      shift 2
      ;;
    --use_qlora)
      QLORA="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1"
      exit 1
      ;;
  esac
done

# Ensure dataset exists, if not generate a tiny placeholder one for testing
if [[ ! -f "$DATASET_PATH" ]]; then
  echo "==> Dataset path '$DATASET_PATH' not found. Generating a small placeholder dataset for validation..."
  mkdir -p "$(dirname "$DATASET_PATH")"
  cat <<EOF > "$DATASET_PATH"
[
  {
    "instruction": "Analyze the business positioning of Acme Corp.",
    "response": "Acme Corp is a leading manufacturer of widgets with a focus on durability."
  },
  {
    "instruction": "Provide marketing recommendations for a fintech startup.",
    "response": "Focus on customer transparency and highlight regulatory compliance in your copy."
  }
]
EOF
fi

# Pick DeepSpeed configuration
if [[ "$DEEFSPEED_STAGE" -eq 3 ]]; then
  DS_CONFIG="infra/deepspeed/ds_config_stage3.json"
else
  DS_CONFIG="infra/deepspeed/ds_config_stage2.json"
fi

QLORA_FLAG=""
if [[ "$QLORA" == "true" ]]; then
  QLORA_FLAG="--use_qlora"
fi

# Load environment variables if .env exists (specifically for HF_HOME cache path)
if [[ -f "$ROOT/.env" ]]; then
  echo "==> Sourcing .env file..."
  set -a
  source "$ROOT/.env"
  set +a
fi

# Activate virtualenv path
export PATH="$ROOT/.venv/bin:$PATH"

echo "========================================================"
echo " Starting BizPulse Fine-Tuning Job"
echo "========================================================"
echo " Model:             $MODEL_ID"
echo " Context Length:    $CONTEXT_LENGTH"
echo " Epochs:            $EPOCHS"
echo " Dataset:           $DATASET_PATH"
echo " GPUs:              $GPUS"
echo " DeepSpeed Config:  $DS_CONFIG"
echo " QLoRA Enabled:     $QLORA"
echo "========================================================"

# Run DeepSpeed trainer
exec deepspeed --include "localhost:$GPUS" scripts/train.py \
  --model_id "$MODEL_ID" \
  --dataset_path "$DATASET_PATH" \
  --context_length "$CONTEXT_LENGTH" \
  --epochs "$EPOCHS" \
  --deepspeed "$DS_CONFIG" \
  $QLORA_FLAG \
  --output_dir "outputs/$(basename "$MODEL_ID")_finetuned"
