# scripts/

Operational helpers for the dev server.

| Script | Purpose |
|---|---|
| `bootstrap_server.sh` | Idempotent first-run setup: install Qdrant binary, install Python deps, create Postgres DB + role + schema. |
| `run_qdrant.sh`       | Start Qdrant binary on `:6333` with `infra/qdrant/config.yaml`. Logs to `logs/qdrant.log`. |
| `init_postgres.sh`    | Create `bizpulse` role + DB on the existing local Postgres at `:5432` (requires `sudo -u postgres`). |
| `run_vllm.sh`         | (deferred — needs free GPU) Start vLLM serving Qwen2.5-14B-Instruct on `:8800`. |
| `run_tei_embed.sh`    | (deferred — needs free GPU) Start TEI serving `bge-large-en-v1.5` on `:8081`. |
| `run_tei_rerank.sh`   | (deferred — needs free GPU) Start TEI serving `bge-reranker-v2-m3` on `:8082`. |
| `status.sh`           | One-shot: `nvidia-smi`, port listeners, service health. Used by `make remote-status`. |

All scripts are intended to be run on the dev server inside a `tmux` session. Logs land under `./logs/` (gitignored).
