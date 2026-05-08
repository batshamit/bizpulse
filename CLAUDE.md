# BizPulse

Multi-agent AI platform that analyzes business websites + social profiles, builds a per-tenant knowledge base, runs a LangGraph reasoning pipeline, and produces a grounded, citation-backed marketing strategy. Multi-tenant by design. Ships with three industry packs: **fintech, real estate, construction materials.**

## Stack

- **Orchestration:** LangGraph
- **LLM inference:** vLLM (OpenAI-compatible) serving `Qwen/Qwen2.5-14B-Instruct` on a Tesla V100-SXM2-32GB. Llama-3.3-70B / Qwen2.5-32B available with tensor-parallel ≥2 if more VRAM is reserved.
- **Embeddings:** Text Embeddings Inference (TEI) serving `BAAI/bge-large-en-v1.5`
- **Reranking:** TEI serving `BAAI/bge-reranker-v2-m3`
- **Vector DB:** Qdrant — hybrid search, per-tenant collections, metadata filtering for isolation
- **Browser automation:** Playwright (consumed via MCP)
- **Web search:** Tavily / Brave (consumed via MCP)
- **HTTP layer:** FastAPI
- **Database:** Postgres 16 (tenant + run metadata)
- **Structured I/O:** Pydantic everywhere
- **MCP:** BizPulse exposes its capabilities AS an MCP server
- **Eval:** custom harness + LLM-as-judge

## Conventions

- Python 3.10+, type hints required, `ruff` + `black` enforced via pre-commit.
- Every agent has: typed input schema, typed output schema, max retry count, fallback model, and a circuit breaker.
- **Multi-tenant isolation enforced at the retrieval layer** — every Qdrant query carries `tenant_id` (and `industry`) as a metadata filter. Skipping the filter is a bug.
- **Every claim in agent output must cite chunk IDs** from retrieval. The Critic agent rejects ungrounded claims.
- **Structured outputs only** — every agent response is validated against a Pydantic schema. JSON parse / schema failure triggers retry with the validation error included in the prompt; second failure falls back to the next model.
- All long-running services exposed over HTTP on the loopback only; reverse proxy if exposed externally.
- Service ports: vLLM `:8800`, TEI embed `:8081`, TEI rerank `:8082`, Qdrant `:6333`, Postgres `:5432` (or `:5433` if running our own instance), FastAPI `:8080`.

## Hardware (target deployment box)

- 8× Tesla V100-SXM2-32GB (NVLink), CUDA 12.2, driver 535.x
- 80 vCPU, 503 GiB RAM, 7 TB on `/raid` (project root: `/raid/amit/mylearning/bizpulse/`)
- Shared multi-tenant lab server — services run as host processes under amit's venv (no system Docker daemon restart). The included `docker-compose.yml` is the portable portfolio reference; deploy it on a clean GPU box for full Docker setup.

## Repo layout

```
.
├── src/bizpulse/         # Python package
│   ├── api/              # FastAPI app
│   ├── agents/           # LangGraph nodes
│   ├── ingest/           # Playwright crawler, chunker
│   ├── retrieval/        # Qdrant client, hybrid search, reranker
│   ├── eval/             # eval harness, LLM-judge
│   ├── mcp/              # BizPulse-as-MCP-server
│   ├── models/           # Pydantic schemas (single source of truth)
│   ├── config.py         # pydantic-settings
│   └── logging.py        # structlog setup
├── industries/           # YAML knowledge packs (fintech, real_estate, construction_materials)
├── infra/                # postgres init.sql, qdrant config, helper scripts
├── tests/                # unit + integration
├── scripts/              # bootstrap_server.sh, eval runners
├── docker-compose.yml    # portfolio reference (deploys cleanly on a clean GPU box)
├── pyproject.toml
├── Makefile
└── README.md
```

## Build phases

| Phase | Focus | Status |
|---|---|---|
| **1** | Foundation: repo skeleton, venv, Postgres schema, Qdrant binary, FastAPI scaffold | in progress |
| 2 | Pydantic core models for ingestion + retrieval + agent I/O | |
| 3 | Ingestion: Playwright crawler → chunker → TEI embed → Qdrant upsert | |
| 4 | Retrieval: hybrid search + reranker + parent-document retrieval | |
| 5 | Industry config packs (3 verticals + 4–5 golden examples each) | |
| 6 | LangGraph multi-agent + Critic loop | |
| 7 | Guided JSON outputs (vLLM `--enable-auto-tool-choice`) | |
| 8 | MCP server exposure (BizPulse-as-MCP) | |
| 9 | FastAPI HTTP layer | |
| 10 | Eval harness (recall@10, MRR, LLM-judge, schema validity) | |
| 11 | Demo: README polish, screencast | |
| (Phase 2) | MiroFish audience simulator as optional terminal node, gated by flag | |

## Working agreements (for Claude Code)

- **Phase-1 gate:** before writing project code, run `nvidia-smi` on the server, confirm GPU + VRAM, recommend the LLM tier, and **wait for explicit confirmation.** Skipping this gate has cost real time before — don't.
- **Tenant isolation is non-negotiable.** Every retrieval includes `tenant_id`. Lint/test for this.
- **Citations are non-negotiable.** Every agent output that asserts a fact about the business cites chunk IDs.
- **Don't fabricate competitors.** Competitor Scout must verify each competitor exists via independent web search before passing it downstream.
- **Don't add features the plan doesn't ask for.** Three similar lines beats premature abstraction. Stick to the phase you're in.
- **Don't introduce backwards-compat shims for code we just wrote.** Refactor cleanly.
- **The server is shared.** Never restart system services, never grab GPUs without checking `nvidia-smi --query-compute-apps`, never `sudo` without flagging it.

## Source of truth

The full project plan (architecture, multi-industry rationale, MCP placement, MiroFish, interview framing) lives in `bizpulse_project_conversation.md`. Re-read it when scope questions arise.
