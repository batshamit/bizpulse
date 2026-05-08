#!/usr/bin/env bash
# Quick situational awareness of the BizPulse host services.
set -uo pipefail

echo "===== nvidia-smi (summary) ====="
nvidia-smi --query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu --format=csv 2>&1 | head -20

echo
echo "===== compute apps ====="
nvidia-smi --query-compute-apps=gpu_uuid,pid,process_name,used_memory --format=csv 2>&1 | head -30

echo
echo "===== bizpulse ports ====="
for p in 6333 6334 8800 8081 8082 8080 5432 5433; do
  if ss -tln 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$p$"; then
    echo "  $p  LISTENING"
  else
    echo "  $p  -"
  fi
done

echo
echo "===== service health ====="
curl -fsS -m 3 http://127.0.0.1:6333/healthz && echo "  qdrant OK" || echo "  qdrant DOWN"
curl -fsS -m 3 http://127.0.0.1:8800/v1/models >/dev/null && echo "  vllm OK" || echo "  vllm DOWN"
curl -fsS -m 3 http://127.0.0.1:8081/health && echo "  tei-embed OK" || echo "  tei-embed DOWN"
curl -fsS -m 3 http://127.0.0.1:8082/health && echo "  tei-rerank OK" || echo "  tei-rerank DOWN"
curl -fsS -m 3 http://127.0.0.1:8080/healthz && echo "  bizpulse-api OK" || echo "  bizpulse-api DOWN"
