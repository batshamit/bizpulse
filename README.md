# BizPulse

> **Give it a company URL → grounded, cited marketing strategy.**
> A multi-agent RAG platform where Claude, Gemini, GPT-4o, Perplexity, Grok, and DeepSeek **debate**, then a synthesizer LLM picks the best answer with citations to the retrieved evidence.

Multi-tenant. Multi-industry (fintech, real estate, construction materials). Self-hosted on an 8× V100 lab server. **98 tests pass** end-to-end against the live Postgres + embedded Qdrant setup.

---

## What's different about this one

Most "multi-agent RAG demos" use one LLM at every step. **BizPulse runs a Council of LLMs** — six different vendors propose, critique each other across rounds, and a designated judge synthesizes the final schema-validated output. The architectural payoff:

- **Hallucination defense.** Five vendors agree the customer's pricing is `₹199/mo`, one says `$199/mo` — the synthesizer flags the outlier instead of writing it.
- **Vendor diversity.** Anthropic outage? OpenAI rate-limit? The Council degrades to N-1 members. We never sit waiting on one provider.
- **Specialization.** Perplexity does Competitor Scout (built-in web search). DeepSeek-R1 does the Critic role (explicit reasoning chains). Grok adds X/Twitter signal where relevant.
- **Demo-ready.** Every agent run records the per-vendor proposals, costs, and minority opinions. The audit trail is the demo.

It still does everything a single-LLM multi-agent system does — orchestration, retrieval, citations, critic loop — just with a more honest model of "what does the LLM think" baked in at every analytical step.

---

## Stack

| Layer | Choice | Why |
|---|---|---|
| **LLM Council** | Anthropic Claude, Google Gemini, OpenAI GPT-4o, Perplexity, xAI Grok, DeepSeek | hallucination defense + vendor diversity |
| **Council debate** | custom (`bizpulse.agents.Council`) | N-round propose → revise → synthesize, peer-only revision prompts |
| **Agent layer** | `bizpulse.agents.AgentRunner` | binds retrieval + prompts + Council + JSON-repair into one call |
| **Embeddings** | TEI + `bge-large-en-v1.5` (when GPU available) | local, 1024-dim, dense |
| **Reranking** | TEI + `bge-reranker-v2-m3` | precision after recall |
| **Vector DB** | Qdrant — embedded for dev, server for demo | hybrid search + metadata filters, **per-tenant collections** |
| **Browser** | Playwright (via MCP) | JS-rendered sites + screenshot fallback |
| **HTTP** | FastAPI | async, OpenAPI / Swagger UI |
| **DB** | Postgres 16 | tenant + run metadata; live on the lab server |
| **Storage backend** | swappable: `InMemoryStore` for dev, `PostgresStore` for prod | `BIZPULSE_STORE` env var picks |
| **Structured I/O** | Pydantic v2 (everywhere) | every agent has a typed input + output schema |
| **Interop** | MCP (BizPulse exposes 11 tools) | platform-as-tool for any MCP client (Claude Desktop, Cursor, etc.) |
| **Orchestration** | LangGraph (Phase 6 follow-up wires the state graph; AgentRunner is the unit it runs) | typed state-machine, retries, deterministic |

---

## What's actually running right now

```bash
ssh amit@exam.dei.ac.in
cd /raid/amit/mylearning/bizpulse
.venv/bin/python -m pytest tests/ -q     # 98 passed
tmux attach -t bizpulse                   # FastAPI live on :8080, --reload mode
```

From your laptop:

```bash
ssh -L 8080:127.0.0.1:8080 amit@exam.dei.ac.in
# then open http://localhost:8080/docs
```

Try it:

```bash
# Create a tenant
curl -X POST http://localhost:8080/v1/tenants \
  -H 'Content-Type: application/json' \
  -d '{"name":"Acme Demo"}'
# -> {"id":"...","name":"Acme Demo","slug":"acme-demo-xxxxxx","api_key":"bzp_..."}

# Register a business + analyze (use the api_key from above)
KEY="bzp_..."
curl -X POST http://localhost:8080/v1/businesses \
  -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com","industry":"fintech"}'

curl -X POST http://localhost:8080/v1/businesses/<id>/analyze \
  -H "X-API-Key: $KEY"
# -> {"id":"...","status":"pending",...}   # the run record persists in Postgres
```

---

## Why this exists (interview talking points)

The platform demonstrates the AI Engineer skill set at depth:

| JD line | Where it lives in the code |
|---|---|
| Multi-agent design with typed roles | `bizpulse.agents.Council`, `AgentRunner`, `prompts.PromptBuilder` |
| RAG pipelines for grounded outputs | `bizpulse.ingest`, `bizpulse.retrieval` (hybrid + reranker + tenant filter) |
| Multi-tenant data isolation | `bizpulse.retrieval.qdrant_repo.TenantQdrant` — one collection per tenant + redundant payload filter; 4 tests including a cross-tenant attack |
| Structured & reliable AI outputs | every agent has Pydantic schema; `AgentRunner` validates + does ONE repair pass on validation failure before raising |
| Failure handling | Council drops failed members and notes them in `minority_opinions`; judge has a fallback; agent has repair loop |
| AI failure debugging | `bizpulse.eval` — golden examples + scorer + LLM-as-judge over a 4-criterion rubric (groundedness, relevance, specificity, actionability) |
| MCP integration | `bizpulse.mcp` exposes 11 tools; `analyze_business`, `query_business_knowledge`, `get_industry_pack`, etc. |

---

## Repo layout

```
bizpulse/
├── src/bizpulse/
│   ├── api/             FastAPI: tenants, businesses, runs, auth
│   ├── agents/          PromptBuilder, Council, AgentRunner
│   ├── ingest/          chunker, IngestionPipeline, Playwright stub
│   ├── retrieval/       TEI clients, TenantQdrant, RetrievalEngine
│   ├── llm/             Anthropic, Gemini, OpenAI-compat × 4 vendors, factory
│   ├── eval/            golden schema, scorer, LLM-judge, EvalRunner
│   ├── mcp/             FastMCP server with 11 tools
│   ├── models/          every Pydantic schema (Tenant, Chunk, Citation,
│   │                    Recommendation, MarketingStrategy, RunRecord, ...)
│   ├── storage/         InMemoryStore + PostgresStore (drop-in)
│   ├── config.py        pydantic-settings
│   └── logging.py       structlog
├── industries/          3 YAML knowledge packs (ontology, regs, channels, addendum)
├── infra/postgres/      init.sql — tenants, businesses, runs, run_steps + demo seed
├── infra/qdrant/        config.yaml
├── scripts/             bootstrap_server, init_postgres, run_*.sh, status,
│                        up.sh / down.sh tmux orchestrators, demo.sh
├── tests/               98 tests, plus tests/eval/golden/<industry>/*.json
├── docker-compose.yml   canonical clean-GPU-box deployment
├── CLAUDE.md            conventions + working agreements
└── pyproject.toml
```

---

## Failure modes by design

The README and demo lead with **failure modes handled**, not features:

- *JS-heavy site → empty crawl* → screenshot OCR fallback (Playwright stub today, Phase-11b real impl).
- *Strategist hallucinates a competitor* → Critic catches via independent web verification, forces retry.
- *Vendor returns malformed JSON* → `AgentRunner._repair` re-prompts the judge with the validation error attached; if that fails too, raise with `raw_text` + `validation_error` for the debug UI.
- *Ungrounded claim* → `Recommendation.evidence_chunk_ids` has Pydantic `min_length=1` constraint. The schema rejects the recommendation before the LLM call returns.
- *Wrong-tenant retrieval* → `TenantQdrant.search()` ALWAYS adds `tenant_id` filter; `upsert()` rejects mismatched chunks; tests cover both.
- *Council member outage* → drop, record in `minority_opinions`, continue with N-1.
- *Judge outage* → fallback judge (configurable); if both fail, raise `CouncilError` so caller knows synthesis didn't happen.

---

## Build status

| Phase | Focus | Status |
|---|---|---|
| 1 | Foundation, FastAPI scaffold, Postgres schema, industry YAMLs | ✅ |
| 2 | Pydantic core models (Tenant, Chunk, Citation, MarketingStrategy, ...) | ✅ |
| 3 | Ingestion: chunker + embedder + tenant-isolated Qdrant + pipeline | ✅ |
| 4 | RetrievalEngine with rerank + safe fallback | ✅ |
| 5 | Industry-pack prompt injection | ✅ |
| 6a | Council debate scaffolding | ✅ |
| 6b | 6 vendor adapters (Anthropic, Gemini, OpenAI, Perplexity, Grok, DeepSeek) | ✅ |
| 6c | AgentRunner with JSON repair loop | ✅ |
| 8 | BizPulse-as-MCP-server (11 tools) | ✅ |
| 9 | FastAPI surface — tenants, businesses, runs, auth | ✅ |
| 9b | PostgresStore (drop-in) — FastAPI persists to PG | ✅ |
| 10 | Eval harness — golden examples, scorer, LLM-judge | ✅ |
| 11a | Live debate (waiting on Anthropic / Gemini API key in `.env`) | ⏳ |
| 11b | Real Playwright crawler (stub today; chromium download pending) | ⏳ |
| 11c | LangGraph state graph wiring of agents | ⏳ |
| (opt) | MiroFish audience simulator as terminal node | ⏳ |

---

## Quickstart (clean GPU box)

```bash
git clone git@github.com:batshamit/bizpulse.git && cd bizpulse
cp .env.example .env                    # fill in vendor keys + Postgres password
docker compose up -d                    # qdrant, postgres, vllm, tei-embed, tei-rerank
make health                             # all green = ready
make demo                               # creates a tenant, kicks off an analyze
```

## License

Proprietary (portfolio submission for AI Engineer @ Bridging Technologies). MIT once shipped.
