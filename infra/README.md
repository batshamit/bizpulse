# infra/

Service-side configuration that's not Python.

| Path | Purpose |
|---|---|
| `postgres/init.sql` | Schema bootstrap. Runs once on a fresh Postgres data volume; for an existing instance, apply manually. |
| `qdrant/config.yaml` | Qdrant runtime config (storage path, ports, telemetry off). Used by `scripts/run_qdrant.sh` when running the binary on a host (not via Docker). |

The Docker Compose deployment in the repo root binds these into the corresponding containers.

For the shared dev server we run Qdrant and Postgres as host processes. See `scripts/run_qdrant.sh` and `scripts/init_postgres.sh`.
