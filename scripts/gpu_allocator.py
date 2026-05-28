#!/usr/bin/env python3
"""
GPU Allocator for BizPulse.
Queries nvidia-smi to find available GPUs (excluding busy ones) and allocates
them dynamically for vLLM, Embedding, and Reranking services.
"""

import argparse
import subprocess
import sys

# Define thresholds for "heavy load"
MEM_FREE_THRESHOLD_MB = 16000  # 16 GB free out of 32 GB
UTIL_THRESHOLD_PCT = 40  # 40% GPU utilization


def get_gpu_status():
    try:
        res = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,memory.total,memory.used,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        gpus = []
        for line in res.stdout.strip().split("\n"):
            if not line:
                continue
            idx, total, used, util = line.split(",")
            idx = int(idx.strip())
            total = int(total.strip())
            used = int(used.strip())
            util = int(util.strip())
            free = total - used
            gpus.append(
                {
                    "index": idx,
                    "total": total,
                    "used": used,
                    "free": free,
                    "util": util,
                }
            )
        return gpus
    except Exception as e:
        print(f"Warning: nvidia-smi failed ({e}). Falling back to defaults.", file=sys.stderr)
        return []


def allocate_gpus():
    gpus = get_gpu_status()
    if not gpus:
        # Fallback if nvidia-smi fails
        return {
            "vllm": {"devices": "0", "tp": 1},
            "embed": {"devices": "0"},
            "rerank": {"devices": "0"},
        }

    # Filter healthy/idle GPUs (not under heavy load)
    healthy = [
        g for g in gpus if g["free"] >= MEM_FREE_THRESHOLD_MB and g["util"] <= UTIL_THRESHOLD_PCT
    ]

    # Sort healthy by free memory descending, then utilization ascending
    healthy.sort(key=lambda g: (-g["free"], g["util"]))
    healthy_indices = [g["index"] for g in healthy]

    # If no healthy GPUs found, fall back to sorting all GPUs by free memory descending
    if not healthy_indices:
        print(
            "Warning: All GPUs are under heavy load. Falling back to least-loaded GPUs.",
            file=sys.stderr,
        )
        gpus.sort(key=lambda g: (-g["free"], g["util"]))
        healthy_indices = [g["index"] for g in gpus]

    num_healthy = len(healthy_indices)

    if num_healthy >= 3:
        # We have at least 3 GPUs. Rerank gets 1, Embed gets 1, vLLM gets the rest.
        rerank_gpu = healthy_indices[-1]
        embed_gpu = healthy_indices[-2]
        vllm_gpus = healthy_indices[:-2]

        # vLLM TP size must be a power of 2 (1, 2, 4, 8)
        tp_size = 1
        for p in [8, 4, 2, 1]:
            if p <= len(vllm_gpus):
                tp_size = p
                break
        vllm_devices = vllm_gpus[:tp_size]

        # Calculate optimal gpu_memory_utilization based on selected vllm devices
        vllm_gpu_objs = [g for g in gpus if g["index"] in vllm_devices]
        util_fractions = []
        for g in vllm_gpu_objs:
            # Leave at least 2048 MB free
            safe_mem = g["free"] - 2048
            util_frac = safe_mem / g["total"]
            util_fractions.append(util_frac)
        gpu_mem_util = min(util_fractions) if util_fractions else 0.85
        gpu_mem_util = max(0.35, min(0.85, round(gpu_mem_util, 2)))

        return {
            "vllm": {
                "devices": ",".join(map(str, vllm_devices)),
                "tp": tp_size,
                "util": gpu_mem_util,
            },
            "embed": {"devices": str(embed_gpu)},
            "rerank": {"devices": str(rerank_gpu)},
        }
    elif num_healthy == 2:
        # 2 GPUs: vLLM on one, Embed + Rerank share the other
        vllm_gpu = healthy_indices[0]
        embed_rerank_gpu = healthy_indices[1]

        vllm_gpu_obj = next(g for g in gpus if g["index"] == vllm_gpu)
        gpu_mem_util = (vllm_gpu_obj["free"] - 2048) / vllm_gpu_obj["total"]
        gpu_mem_util = max(0.35, min(0.85, round(gpu_mem_util, 2)))

        return {
            "vllm": {"devices": str(vllm_gpu), "tp": 1, "util": gpu_mem_util},
            "embed": {"devices": str(embed_rerank_gpu)},
            "rerank": {"devices": str(embed_rerank_gpu)},
        }
    else:
        # 1 GPU: All services share it
        gpu = healthy_indices[0]

        gpu_obj = next(g for g in gpus if g["index"] == gpu)
        gpu_mem_util = (gpu_obj["free"] - 6144) / gpu_obj["total"]
        gpu_mem_util = max(0.35, min(0.70, round(gpu_mem_util, 2)))

        return {
            "vllm": {"devices": str(gpu), "tp": 1, "util": gpu_mem_util},
            "embed": {"devices": str(gpu)},
            "rerank": {"devices": str(gpu)},
        }


def main():
    parser = argparse.ArgumentParser(description="Allocate GPUs dynamically for BizPulse services.")
    parser.add_argument(
        "--service",
        choices=["vllm", "embed", "rerank", "all"],
        required=True,
        help="The service to get allocation for.",
    )
    args = parser.parse_args()

    allocation = allocate_gpus()

    if args.service == "vllm":
        v = allocation["vllm"]
        print(
            f"CUDA_VISIBLE_DEVICES={v['devices']} TENSOR_PARALLEL_SIZE={v['tp']} GPU_MEMORY_UTILIZATION={v['util']}"
        )
    elif args.service == "embed":
        e = allocation["embed"]
        print(f"CUDA_VISIBLE_DEVICES={e['devices']}")
    elif args.service == "rerank":
        r = allocation["rerank"]
        print(f"CUDA_VISIBLE_DEVICES={r['devices']}")
    elif args.service == "all":
        for svc, info in allocation.items():
            print(f"{svc}: devices={info.get('devices')} tp={info.get('tp', 'N/A')}")


if __name__ == "__main__":
    main()
