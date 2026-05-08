# BizPulse — AI Engineer Project Plan

> A complete record of the project ideation, architecture, and build plan for the **AI Engineer** role at Bridging Technologies, designed to be built on a self-hosted NVIDIA GPU server using Claude Code.

---

## Table of Contents

1. [The Job Context](#1-the-job-context)
2. [The Project Idea — BizPulse](#2-the-project-idea--bizpulse)
3. [Multi-Industry Support](#3-multi-industry-support)
4. [The Vector Database Layer](#4-the-vector-database-layer)
5. [MCP Server Integration](#5-mcp-server-integration)
6. [Connecting to the NVIDIA Server + Claude Code Setup](#6-connecting-to-the-nvidia-server--claude-code-setup)
7. [The First Concrete Prompt for Claude Code](#7-the-first-concrete-prompt-for-claude-code)
8. [MiroFish AI as an Optional Simulation Layer](#8-mirofish-ai-as-an-optional-simulation-layer)
9. [Final Stack Summary](#9-final-stack-summary)

---

## 1. The Job Context

The role is **AI Engineer at Bridging Technologies** (California-based fintech + SaaS company). Key responsibilities from the JD:

- Designing multi-agent AI systems with clear roles, control flows, and failure handling
- Building RAG pipelines for business insights, content analysis, and recommendations
- Creating high-precision prompts for structured, reliable AI outputs
- Analyzing business websites, social media content, and internal platform data
- Ensuring AI outputs are grounded, accurate, and production-safe
- Multi-tenant data isolation
- Debugging AI failures (hallucinations, wrong reasoning, bad retrieval)

**Hardware available:** A self-hosted NVIDIA GPU server, which lets us run local LLMs, embeddings, and vector DBs without paying per-token API costs.

---

## 2. The Project Idea — BizPulse

**One-line pitch:** Give it a company's website URL. It crawls the site + social profiles, builds a private knowledge base, runs a multi-agent reasoning pipeline, and produces a grounded, structured marketing strategy report — with citations, confidence scores, and a fallback path when any agent fails.

This single project hits ~90% of the JD checkboxes.

### System Architecture

#### 1. Ingestion Layer (Browser Automation)
- **Playwright crawler** that handles JS-rendered sites, takes full-page screenshots, extracts DOM text, meta tags, pricing pages, blog posts.
- Separate scrapers for public LinkedIn company pages, X/Twitter profiles, Instagram bios + recent posts.
- Store raw HTML, screenshots, and extracted text in object storage with content hashes to avoid re-crawling.

#### 2. RAG Layer (Retrieval Core)
- Run embeddings locally on the NVIDIA box — `bge-large-en-v1.5` or `nomic-embed-text-v1.5` via vLLM or Text Embeddings Inference.
- Vector DB: **Qdrant** (self-hosted on the same server). Use **hybrid search** (BM25 + dense).
- **Multi-tenant isolation** — every business gets a namespaced collection with a `tenant_id` filter enforced at query time.
- Chunk strategy: structured chunking by section (hero, pricing, about, blog post) with metadata. Add parent-document retrieval.

#### 3. Multi-Agent Layer (LangGraph)
Build with **LangGraph**. Define agents as nodes in a state graph:

- **Orchestrator agent** — reads input, plans which sub-agents to call, routes work.
- **Brand analyst** — extracts positioning, tone, value props from the website RAG.
- **Audience analyst** — infers ICP from copy, testimonials, case studies.
- **Competitor scout** — searches the web for 3–5 competitors, runs the same crawl on them, compares.
- **Content auditor** — analyzes social posts for engagement patterns, content pillars, gaps.
- **Strategist** — synthesizes everything into the final structured output.
- **Critic/grounding agent** — re-reads the strategist's output and verifies every claim is backed by a retrieved chunk; flags ungrounded claims for retry.

Each agent has: typed input schema, typed output schema (Pydantic), max retry count, fallback model, and a circuit breaker.

#### 4. Structured Output Contract
Every agent returns strict JSON validated against Pydantic schemas. Final output:

```json
{
  "brand": { "...": "..." },
  "audience": { "...": "..." },
  "competitive_landscape": ["..."],
  "recommendations": [
    {
      "channel": "...",
      "action": "...",
      "rationale": "...",
      "evidence_chunk_ids": ["..."],
      "confidence": 0.87
    }
  ]
}
```

Every recommendation must cite the chunk IDs that support it. **No citation = rejected by the critic agent.**

#### 5. Local LLM Serving
Serve `Qwen2.5-32B-Instruct` or `Llama-3.3-70B` via **vLLM** with structured output (guided JSON via outlines or vLLM's guided decoding). Keep an Anthropic/OpenAI fallback for high-stakes synthesis.

#### 6. Evaluation Pipeline
- 20–30 hand-labeled "golden" businesses
- Automated checks: groundedness, schema validity, latency, cost per run
- LLM-as-judge for qualitative scoring with a rubric
- Track metrics over time (LangSmith or Postgres + Streamlit)

#### 7. Failure Observability
Log every agent step, retrieval result, prompt/response pair. Build a debug UI to replay failed runs.

### Framing in Interview / README
Frame the project around **failure modes you handled**, not features:
- *"When the website is JS-heavy and the crawler returns empty text, the system falls back to screenshot OCR."*
- *"When the strategist hallucinates a competitor that doesn't exist, the critic catches it via web verification and forces a retry."*
- *"When the local LLM's JSON output is malformed, we re-prompt with the validation error attached, then fall back to Anthropic if it still fails."*

---

## 3. Multi-Industry Support

The project supports multiple verticals: **fintech, real estate, automobile, electrical, interior construction, construction materials.**

A multi-industry platform is more impressive than a single-industry tool — it shows the same thing the company sells: one AI engine, many verticals.

### Architecture Changes

#### 1. Industry Classifier
A lightweight agent that runs after crawling. Classifies the business into one of the supported verticals with a confidence score.

#### 2. Industry Knowledge Packs
Each vertical gets its own config bundle (YAML/JSON):

- **Domain ontology** — entities and concepts that matter (real estate: RERA, carpet area, possession date; automobile: model year, fuel type, dealer network; construction materials: MOQ, IS codes, B2B vs retail).
- **Competitor seed list** — known players in that vertical.
- **Channel weights** — Instagram + YouTube heavy for real estate/automobile; LinkedIn + trade pubs for construction materials.
- **KPIs** — site visits + walk-ins (real estate), test drives + showroom footfall (automobile), RFQs + dealer signups (construction materials).
- **Compliance flags** — RBI/SEBI (fintech), RERA (real estate), emission norms (automobile).

#### 3. Industry-Specific Prompts
The Strategist gets a base prompt + industry addendum injected at runtime.

#### 4. Industry-Specific Eval Sets
4–5 golden examples per vertical so you can measure performance per industry and fix gaps surgically.

### Recommended Scope
Build the platform to support N verticals, but ship with **3 well-tested ones**:
1. **Fintech** (B2C, regulated, digital-first) — matches company's core
2. **Real estate** (B2C, high-ticket, local, visual) — different content patterns
3. **Construction materials** (B2B, technical, channel-driven) — proves you handle B2B

Then frame in README: *"The system is designed to onboard a new vertical in under a day by adding one config file and 3–5 eval examples."*

---

## 4. The Vector Database Layer

**Yes, the vector DB is core to the project.** It's the *memory* of the system.

### Why It's Needed
A business website crawl pulls hundreds of pages. You can't stuff all of that into an LLM context window for every agent call. So you:
1. Chunk the content intelligently
2. Embed it (turn each chunk into a vector)
3. Store those vectors in a queryable DB
4. At reasoning time, retrieve only the 5–15 most relevant chunks

### Choice: Self-Hosted Qdrant
- Self-hosted on the NVIDIA server signals you can run infra, not just call SaaS APIs.
- Qdrant has excellent metadata filtering (critical for multi-tenancy), native hybrid search, clean Python client.
- Pinecone is fine but it's managed — using it doesn't prove infra skills.
- FAISS is a library, not a database — skip it for production.

### Pipeline Integration

**Ingestion time:**
1. Playwright crawls website → raw HTML, screenshots, extracted text
2. Chunker splits content semantically with metadata (`tenant_id`, `industry`, `source_type`, `url`, `crawled_at`)
3. Embedder runs `bge-large-en-v1.5` locally on GPU via TEI
4. Vectors + metadata upserted into per-tenant Qdrant collections

**Reasoning time:**
1. Agent asks: *"What's this company's positioning?"*
2. Query embedded into same vector space
3. Qdrant returns top-K chunks **filtered by tenant_id + source_type**
4. Chunks (with source URLs) passed into agent's prompt as grounded context
5. Agent's output cites chunk IDs — Critic verifies every claim traces back

### Senior-Level Implementation Details

1. **Hybrid search, not pure dense.** BM25 + dense + reranking. Pure vector search misses exact-match queries (e.g., "RERA No: P51700001234").
2. **Metadata filtering for multi-tenancy.** Every query includes `tenant_id = "biz_42" AND industry = "real_estate"`. Get this wrong = data leak between tenants = fireable offense for fintech SaaS.
3. **Parent-document retrieval.** Embed small chunks (better recall) but return larger parent sections (better context).
4. **Reranking layer.** After top-20 from Qdrant, rerank with `bge-reranker-v2-m3`. Pick best 5.
5. **Industry-aware retrieval.** Boost domain-relevant source types per industry.
6. **Freshness and re-indexing.** `crawled_at` timestamp + 7-day re-crawl with content hash diffing.

### Interview Framing
> *"I self-hosted Qdrant on the same NVIDIA server running my embedding model and LLM, so retrieval latency stayed under 50ms even with hybrid search and reranking. I used per-tenant collections with metadata filters for isolation, parent-document retrieval to reduce hallucination, and industry-tagged chunks so the retriever could bias toward domain-relevant sources. I evaluated retrieval quality separately from generation quality using recall@10 and MRR — because if retrieval is bad, no prompt tuning will save you."*

---

## 5. MCP Server Integration

**MCP (Model Context Protocol)** is an open standard from Anthropic that lets LLMs/agents talk to external tools through a uniform interface. "USB-C for AI tools."

### Where MCP Fits in BizPulse

#### 1. Expose BizPulse Itself AS an MCP Server (Most Impressive)
Wrap platform capabilities as an MCP server so any MCP-compatible client (Claude Desktop, Cursor, customer agents) can use them:

- `analyze_business(url)` → triggers the full pipeline
- `get_competitive_landscape(business_id)` → returns competitor analysis
- `get_marketing_recommendations(business_id, channel)` → scoped recommendations
- `query_business_knowledge(business_id, question)` → RAG query against tenant's vector store

This shows you understand AI products in 2026 aren't just chat UIs — they're **interoperable agent capabilities**.

#### 2. Consume External MCP Servers (Practical)
- **Playwright MCP server** for browser automation
- **Brave Search / Tavily MCP** for the Competitor Scout agent's web research
- **Filesystem MCP** for managing crawled artifacts and screenshots
- **Postgres MCP** for letting agents query tenant's structured data
- **Gmail / Slack MCP** for "send strategy report to stakeholders" features

This maps to the JD line: *"AI-driven automation across SaaS workflows."*

#### 3. Multi-Tenant Data Access via MCP
Per-tenant MCP server exposes only that tenant's data. Agent gets a scoped MCP connection, not raw DB credentials. Auth enforced at the MCP layer. Direct mapping to *"Ensure data isolation in multi-tenant environments."*

### Where NOT to Use MCP
- **Internal agent-to-agent communication** — LangGraph nodes call each other through state graph, not MCP.
- **Vector DB** — Qdrant has a native client. No need to wrap it.
- **LLM inference itself** — vLLM is just an OpenAI-compatible endpoint.

### Recommendation: 2 Well-Placed MCP Integrations

**(a)** Build BizPulse itself as an MCP server. Expose 4–6 high-value tools. Demo by connecting Claude Desktop to your local MCP server: *"Hey Claude, analyze acme-realty.com and tell me their top 3 marketing gaps."* Claude calls your MCP server, runs the full pipeline. **Electric demo.**

**(b)** Use 1–2 existing MCP servers (Playwright, Tavily) for tool calls.

### Interview Framing
> *"I built BizPulse with MCP as the interoperability layer. The platform exposes its capabilities as an MCP server so it can be driven by any MCP-compatible client. Internally, agents use existing MCP servers like Playwright and Tavily so I'm not reinventing browser automation or web search. The internal multi-agent orchestration is done in LangGraph because MCP isn't designed for tightly-coupled state machines. I think a lot of teams overuse MCP — I tried to put it only at the boundaries where interoperability actually matters."*

---

## 6. Connecting to the NVIDIA Server + Claude Code Setup

### Phase 1: Connect to the Server

#### Step 1. Get Access Details
- Public IP or hostname
- Username (usually `ubuntu` or `root`)
- SSH key (`.pem` or `id_rsa`)

```bash
chmod 600 ~/.ssh/nvidia_server.pem
```

#### Step 2. SSH In and Verify GPU
```bash
ssh -i ~/.ssh/nvidia_server.pem ubuntu@<server-ip>

nvidia-smi                                                                     # Driver check
nvcc --version                                                                  # CUDA toolkit
docker --version                                                                # Docker
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi       # GPU in Docker
```

#### Step 3. SSH Config (Optional but Worth It)
On laptop, edit `~/.ssh/config`:
```
Host nvidia
    HostName <server-ip>
    User ubuntu
    IdentityFile ~/.ssh/nvidia_server.pem
    ServerAliveInterval 60
```
Now connect with just `ssh nvidia`.

#### Step 4. Port Forwarding for Local Dev
```bash
ssh -L 8000:localhost:8000 \
    -L 6333:localhost:6333 \
    -L 8080:localhost:8080 \
    nvidia
```

Use **tmux** for long-running sessions:
```bash
tmux new -s bizpulse
# do work; detach with Ctrl+B then D
# reattach: tmux attach -t bizpulse
```

### Phase 2: Where Claude Code Runs (3 Options)

- **Option A:** Claude Code locally on laptop, push code to server.
- **Option B:** Claude Code directly on server via SSH.
- **Option C (recommended):** VS Code Remote-SSH + Claude Code in remote session.

### Phase 3: VS Code Remote-SSH + Claude Code

#### Step 5. Install Remote-SSH
1. Install VS Code on laptop.
2. Install **Remote - SSH** extension.
3. F1 → "Remote-SSH: Connect to Host" → pick `nvidia`.
4. Open folder `/home/ubuntu/bizpulse`.

#### Step 6. Install Claude Code on Server
```bash
curl -fsSL https://claude.ai/install.sh | bash
```
Reopen terminal, then:
```bash
claude --version
claude    # follow login prompt
```
Requires Claude Pro/Max or Anthropic Console credits — free tier doesn't include Claude Code.

For headless servers: `export ANTHROPIC_API_KEY="sk-ant-..."`

#### Step 7. Initialize the Project
```bash
mkdir -p /home/ubuntu/bizpulse
cd /home/ubuntu/bizpulse
git init
claude
```

Inside Claude Code, run `/init` to create `CLAUDE.md`. Then edit it:

```markdown
# BizPulse

Multi-agent AI platform that analyzes business websites and generates
marketing strategies. Multi-tenant, supports fintech, real estate,
automobile, electrical, interior construction, and construction materials.

## Stack
- LangGraph for orchestration
- vLLM serving Qwen2.5-32B-Instruct on local GPU
- Qdrant for vector storage (self-hosted)
- BGE embeddings via Text Embeddings Inference
- MCP server exposes platform capabilities
- FastAPI HTTP layer
- Postgres for tenant + run metadata
- Playwright for browser automation
- Pydantic for all structured I/O

## Conventions
- Python 3.11, type hints required, ruff + black
- Every agent has: input schema, output schema, retry policy, fallback path
- Multi-tenant isolation enforced at retrieval layer (tenant_id filter)
- Every claim in agent output must cite chunk IDs from retrieval
- All services run via Docker Compose; GPU services use --gpus all

## Hardware
- NVIDIA GPU server
- Local services: vLLM on :8000, Qdrant on :6333, FastAPI on :8080
```

### Phase 4: The Build Sequence (Driven by Prompts)

The build proceeds through 12 prompt-driven steps:

1. Foundation — Docker Compose
2. Python project skeleton
3. Core data models
4. Ingestion + chunking + embedding
5. Retrieval layer
6. Industry config packs
7. Multi-agent graph (LangGraph)
8. Structured outputs with guided decoding
9. MCP server
10. FastAPI HTTP layer
11. Eval harness
12. Demo

### Phase 5: Operational Hygiene

- **Use tmux** so model downloads/builds survive laptop sleep.
- **Watch GPU memory:** `watch -n 1 nvidia-smi` in side pane.
- **Commit frequently** — Claude Code can change many files at once.
- **`/cost` command** in Claude Code — track token usage.
- **`--dangerously-skip-permissions`** only for sandboxed long runs, never with prod creds.
- **Git worktrees** for parallel agent design experiments.

### Mental Model

```
Your laptop                          NVIDIA Server
-----------                          -------------
VS Code (Remote-SSH client) ───SSH──▶ VS Code Server
Browser (Qdrant UI)         ──tunnel─▶ Qdrant :6333
Browser (FastAPI docs)      ──tunnel─▶ FastAPI :8080
Claude Desktop (MCP client) ──tunnel─▶ Your MCP server
                                       ├── vLLM :8000 (GPU)
                                       ├── TEI embeddings :8081 (GPU)
                                       ├── Qdrant :6333
                                       ├── Postgres :5432
                                       └── Claude Code CLI (drives the build)
```

---

## 7. The First Concrete Prompt for Claude Code

This is the exact prompt to paste into Claude Code after running `claude` inside `/home/ubuntu/bizpulse` and creating `CLAUDE.md`.

### The Prompt

> Read CLAUDE.md first to understand the project, then run `nvidia-smi` to see what GPU we're working with. Don't write any code yet — first reply with: (1) the GPU model and VRAM you detected, (2) which LLM you'd recommend serving locally given that VRAM (Qwen2.5-32B-Instruct if we have ≥48GB, Qwen2.5-14B-Instruct if 24–48GB, Qwen2.5-7B-Instruct if less), (3) any concerns about the plan below. Wait for my confirmation before writing files.
>
> **Goal:** set up the foundational service layer for BizPulse via Docker Compose. This is infrastructure only — no application code yet.
>
> **Services to define:**
>
> 1. **Qdrant** — image `qdrant/qdrant:latest`, expose ports 6333 (HTTP) and 6334 (gRPC), persist data to a named volume `qdrant_storage`, healthcheck on `/healthz`.
>
> 2. **Postgres 16** — image `postgres:16-alpine`, port 5432, named volume `pg_data`, env vars from `.env`, init script in `infra/postgres/init.sql` that creates a `bizpulse` database with two starter tables: `tenants(id uuid pk, name text, api_key text unique, created_at timestamptz)` and `businesses(id uuid pk, tenant_id uuid fk, url text, industry text, status text, created_at timestamptz)`.
>
> 3. **Text Embeddings Inference (TEI)** — image `ghcr.io/huggingface/text-embeddings-inference:latest`, serving `BAAI/bge-large-en-v1.5`, port 8081, with `--gpus all` and a model cache volume.
>
> 4. **vLLM** — image `vllm/vllm-openai:latest`, OpenAI-compatible API on port 8000, serve the model recommended in step (2), with `--gpus all`, model cache volume, `--max-model-len 8192`, `--gpu-memory-utilization 0.85`, `--enable-auto-tool-choice` and `--tool-call-parser hermes`. Set `HF_HUB_ENABLE_HF_TRANSFER=1`.
>
> 5. **TEI Reranker** — second TEI instance on port 8082 serving `BAAI/bge-reranker-v2-m3`, with `--gpus all` and its own cache volume.
>
> **Files to create:**
> - `docker-compose.yml` at repo root
> - `.env.example` with all required variables
> - `.gitignore`
> - `infra/postgres/init.sql`
> - `Makefile` with: `up`, `down`, `logs`, `ps`, `restart`, `clean` (requires confirmation), `gpu`, `health`
> - `README.md`
> - `infra/README.md`
>
> **Constraints:**
> - GPU services must use `deploy.resources.reservations.devices` (modern compose), not `runtime: nvidia`.
> - All services on a `bizpulse-net` bridge network.
> - Healthchecks on every service.
> - Named volumes for all persistent data — no bind mounts.
> - Memory limits on Postgres (1GB) and Qdrant (4GB); none on GPU services.
> - `restart: unless-stopped` on every service.
>
> **After files are written:** Don't run `make up` yet. Summarize: (a) services and ports, (b) total VRAM consumption estimate, (c) decisions to review, (d) next prompt to give.

### Why This Prompt Works

1. **Pre-flight check** forces reading `CLAUDE.md` and running `nvidia-smi` first.
2. **"Wait for confirmation"** gate prevents runaway file generation.
3. **Conditional model recommendation** signals expectation of judgment.
4. **Specificity** on `--max-model-len`, `--gpu-memory-utilization`, `--enable-auto-tool-choice` — these settings make vLLM usable for guided JSON later.
5. **Modern compose syntax** instruction prevents legacy `runtime: nvidia`.
6. **`make health` target** becomes the single command for sanity-checking the stack.
7. **"Don't run make up yet"** prevents kicking off 30–60GB model downloads before review.
8. **"Next prompt" hint** keeps mental models aligned.

### Validation Checklist Before `make up`

- [ ] 5 services defined; all GPU services use `deploy.resources.reservations.devices`
- [ ] vLLM has `--enable-auto-tool-choice` and `--tool-call-parser hermes`
- [ ] Healthchecks on every service
- [ ] `.env.example` has only placeholders
- [ ] `.gitignore` excludes `.env`
- [ ] All volumes are **named volumes**
- [ ] `clean` target requires confirmation
- [ ] Estimated VRAM < actual VRAM with ≥2GB headroom

### Launch Sequence

```bash
cp .env.example .env
# edit .env

make up
make logs                     # tail in another tmux pane
watch -n 2 nvidia-smi         # watch VRAM fill as model loads

make health                   # all green = ready

# Smoke tests:
curl http://localhost:6333/healthz
curl http://localhost:8000/v1/models
curl http://localhost:8081/health
curl http://localhost:8082/health
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"<model>","messages":[{"role":"user","content":"Say hello in one word."}]}'
```

### Common First-Run Issues

- **`could not select device driver`** → install NVIDIA Container Toolkit:
  ```bash
  sudo apt install -y nvidia-container-toolkit
  sudo nvidia-ctk runtime configure --runtime=docker
  sudo systemctl restart docker
  ```
- **vLLM hangs on "Loading model"** → it's downloading. Check `df -h` and `nvidia-smi`.
- **vLLM OOM** → drop one model tier or use `--quantization awq`.
- **Postgres init script doesn't run** → only runs on fresh volume. `make clean` then retry.

---

## 8. MiroFish AI as an Optional Simulation Layer

**MiroFish** is the open-source swarm-intelligence prediction engine (built by Guo Hangjiang, viral on GitHub in March 2026). Powered by the **OASIS framework** from CAMEL-AI. Spawns thousands of AI agents with personalities and memories that interact in simulated Twitter/Reddit-like environments, producing prediction reports from emergent dynamics.

### Where It Fits — and Where It Doesn't

| | BizPulse Core Multi-Agent | MiroFish |
|---|---|---|
| **Goal** | Convergent — one grounded, cited strategy | Divergent — emergent crowd dynamics |
| **Output** | Schema-validated, citation-required | Statistical, narrative report |
| **Agents** | 5–7 specialized roles | Hundreds to thousands of personas |
| **Use case** | Production analysis | Pre-launch simulation |

**Don't replace BizPulse's analysis pipeline with MiroFish.** You'd lose citations, schema-validated outputs, groundedness checks — every property the JD asks for.

### The One Place It Fits Beautifully — Campaign Pre-Launch Validator

Add it as an **optional terminal node** in the LangGraph state machine:

```
ingest → industry_classifier → orchestrator
  → [brand, audience, competitor, content] (parallel)
  → strategist
  → critic
  → [optional] audience_simulator (MiroFish)         ← NEW
  → [optional] strategist_refinement_loop            ← NEW
  → final_output
```

**Flow:**
1. Strategist generates a campaign (e.g., *"First-time homebuyer guarantee, tier-2 cities, Instagram Reels"*)
2. Audience Simulator spins up a few hundred agents matching the target ICP
3. Agents "see" the campaign in a simulated Instagram-like environment; system observes engagement, objections, sharing
4. Findings fed back to Strategist for refinement (e.g., *"60% of agents flagged 'guarantee' as legally suspect under RERA; lead with EMI calculators instead"*)

### Practical Concerns

1. **GPU contention** — thousands of agent calls saturate the GPU. Queue as background jobs or use a smaller model (Qwen2.5-7B) for simulation agents while the main pipeline uses 32B.
2. **Zep Cloud dependency** — MiroFish uses Zep Cloud for memory by default. Self-host Zep to keep the "fully local" story; otherwise note as production gap.
3. **Maturity** — brand new (March 2026). Pin commits, don't auto-upgrade, have a fallback (lightweight 10–20 agent "synthetic focus group" using your own code).
4. **Don't over-claim** — simulation results are noisy. Critic treats MiroFish output as *advisory*, not ground truth. Phrase as *"simulated audience reaction suggests..."*

### Recommendation

Build BizPulse's core first — that's what gets the job. Then **as Phase 2**, add MiroFish as the optional Audience Simulator. Demo both: deterministic pipeline producing a strategy, then simulation refining it. The contrast makes the demo memorable.

### Interview Framing

> *"The core pipeline is a deterministic, grounded RAG-and-agent system that produces cited marketing strategies. For B2C verticals, I added an optional simulation step using MiroFish — after the strategist generates a campaign, I spin up a few hundred agents matching the target ICP and watch how they react in a simulated social environment. It surfaces failure modes that pure analysis misses, like a campaign tagline that triggers regulatory red flags. The key design decision was keeping it isolated as a refinement loop rather than letting emergent simulation pollute the grounded output — simulation is advisory, not authoritative. I also kept it optional and gated behind a flag because it's compute-expensive and not all industries benefit."*

---

## 9. Final Stack Summary

| Layer | Technology |
|---|---|
| **Orchestration** | LangGraph |
| **LLM Inference** | vLLM (Qwen2.5-32B / Llama-3.3-70B) — local GPU |
| **Embeddings** | TEI + `bge-large-en-v1.5` — local GPU |
| **Reranking** | TEI + `bge-reranker-v2-m3` — local GPU |
| **Vector DB** | Qdrant (self-hosted, hybrid search) |
| **Browser Automation** | Playwright (via MCP) |
| **Web Search** | Tavily / Brave (via MCP) |
| **Interop Layer** | MCP (BizPulse exposes server + consumes external) |
| **Structured I/O** | Pydantic + vLLM guided JSON |
| **HTTP Layer** | FastAPI |
| **Database** | Postgres 16 |
| **Optional Simulation** | MiroFish (Phase 2 add-on, gated by flag) |
| **Eval** | Custom harness + LLM-as-judge + LangSmith |
| **Local Dev** | Docker Compose |
| **Production-aspirational** | Kubernetes |
| **Coding Tool** | Claude Code on the NVIDIA server via VS Code Remote-SSH |

---

## Build Roadmap

| Phase | Focus | Duration |
|---|---|---|
| **1** | Docker Compose foundation, Python skeleton, models | Week 1 |
| **2** | Ingestion, RAG, retrieval | Week 1–2 |
| **3** | Single-agent baseline | Week 2 |
| **4** | Multi-agent LangGraph + Critic loop | Week 3 |
| **5** | MCP server + FastAPI | Week 3 |
| **6** | Eval harness + 3 industry packs | Week 4 |
| **7** | Demo video + README polish | Week 4 |
| **8 (optional)** | MiroFish Audience Simulator | Week 5 |

---

*End of project plan. Next step: paste the Phase 1 prompt into Claude Code on the NVIDIA server and begin the build.*
