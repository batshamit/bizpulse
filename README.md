# BizPulse

> Give it a company URL → grounded, cited marketing strategy via a multi-agent RAG pipeline. Multi-tenant, multi-industry, self-hosted.

BizPulse crawls a business website + social profiles, builds a per-tenant knowledge base in Qdrant, runs a LangGraph multi-agent reasoning pipeline (orchestrator → brand / audience / competitor / content analysts → strategist → critic), and emits a schema-validated marketing strategy where every claim cites the retrieved chunk IDs that support it.

## Stack

| Layer | Choice | Why |
|---|---|---|
| Orchestration | **LangGraph** | typed state-machine, retries, deterministic |
| LLM serving | **vLLM** (Qwen2.5-14B-Instruct, OpenAI-compatible) | fast self-hosted inference; guided JSON via `--enable-auto-tool-choice` |
| Embeddings | **TEI** + `bge-large-en-v1.5` | local, 1024-dim, dense |
| Reranking | **TEI** + `bge-reranker-v2-m3` | precision after recall |
| Vector DB | **Qdrant** (self-hosted) | hybrid search + metadata filters, **per-tenant collections** |
| Browser | **Playwright** (via MCP) | JS-rendered sites + screenshot fallback |
| Web search | **Tavily / Brave** (via MCP) | Competitor scout |
| HTTP | **FastAPI** | async, OpenAPI |
| DB | **Postgres 16** | tenant + run metadata |
| Structured I/O | **Pydantic** | every agent has typed input + output |
| Interop | **MCP** (BizPulse exposes a server) | platform-as-tool for any MCP client |

## Why this exists

The platform demonstrates the full AI Engineer skill set on real hardware:

- **Multi-agent design** — typed roles, retries, fallbacks, circuit breakers, a Critic that rejects ungrounded claims.
- **RAG done seriously** — hybrid (BM25 + dense) search, reranker, parent-document retrieval, per-tenant metadata filtering, evaluated independently from generation.
- **Multi-tenant data isolation** — every retrieval enforces `tenant_id`. Wrong filter = data leak; we treat that as a fireable-offense bug and have tests for it.
- **Failure handling** — every agent has explicit max retries, fallback model, schema validation. Ungrounded outputs get rejected and re-prompted with the validation error attached.
- **Multi-industry** — three verticals ship: **fintech, real estate, construction materials.** Each has a YAML knowledge pack (ontology, competitor seeds, channel weights, KPIs, compliance flags) so onboarding a new vertical is a one-day exercise.
- **MCP at the right boundaries** — platform exposes capabilities as an MCP server (interop), consumes Playwright + Tavily as MCP clients (don't reinvent), but internal agent-to-agent comms stay in LangGraph state.

## Quickstart (clean GPU box)

The repo's `docker-compose.yml` is the canonical deployment for any clean machine with NVIDIA Container Toolkit:

```bash
git clone https://github.com/batshamit/bizpulse.git && cd bizpulse
cp .env.example .env                    # fill in values
docker compose up -d                    # brings up qdrant, postgres, vllm, tei-embed, tei-rerank
make health                             # all green = ready
```

## Quickstart (this dev environment — shared multi-tenant server)

The actual development box is a shared lab server with 8× V100s where Docker `data-root` lives on a 100%-full root partition we don't own. So we run services as host processes under `/raid/amit/mylearning/bizpulse/`:

```bash
ssh amit@exam.dei.ac.in
cd /raid/amit/mylearning/bizpulse
source .venv/bin/activate
pip install -e ".[dev]"

# Qdrant standalone binary, pointed at /raid for data
./scripts/run_qdrant.sh &

# Postgres: use existing :5432 with a bizpulse DB, or run our own on :5433
./scripts/init_postgres.sh

# When a GPU is free:
./scripts/run_vllm.sh                   # serves Qwen2.5-14B on :8800
./scripts/run_tei_embed.sh              # bge-large-en-v1.5 on :8081
./scripts/run_tei_rerank.sh             # bge-reranker-v2-m3 on :8082

# API
uvicorn bizpulse.api.main:app --host 127.0.0.1 --port 8080
```

From your laptop, forward the ports:

```bash
make remote-tunnel                      # forwards 6333, 8080, 8800, 8081, 8082
```

## Repo layout

See [CLAUDE.md](CLAUDE.md) for the canonical layout, conventions, and phase plan.

## Build phases

| Phase | Focus |
|---|---|
| 1 | Repo skeleton, venv, Postgres schema, Qdrant binary, FastAPI scaffold |
| 2 | Pydantic core models |
| 3 | Ingestion → chunking → embedding → Qdrant upsert |
| 4 | Hybrid retrieval + reranker + parent-document |
| 5 | Industry config packs (3 verticals + golden eval examples) |
| 6 | LangGraph multi-agent + Critic loop |
| 7 | Guided JSON outputs |
| 8 | MCP server exposure |
| 9 | FastAPI HTTP layer |
| 10 | Eval harness (recall@10, MRR, LLM-judge, schema validity) |
| 11 | Demo polish |
| 12 | (Optional) MiroFish audience simulator as flagged terminal node |

## Failure modes by design

The README and demo lead with **failure modes handled**, not features:

- *JS-heavy site → empty crawl* → falls back to screenshot OCR.
- *Strategist hallucinates a competitor* → Critic catches it via independent web verification, forces retry.
- *vLLM returns malformed JSON* → re-prompt with the validation error attached; if a second attempt fails, fall back to Anthropic.
- *Ungrounded claim* → Critic rejects, requires citation chunk IDs from retrieval.
- *Wrong-tenant retrieval* → tests assert every Qdrant query carries `tenant_id`; CI fails otherwise.

## License

MIT.
