# BizPulse Project Instructions (Antigravity 2.0)

Multi-agent AI platform for business analysis and marketing strategy generation.

## Foundational Mandates

- **Tenant Isolation:** Mandatory at the retrieval layer. Every Qdrant query MUST carry `tenant_id` and `industry` as metadata filters. NEVER skip these filters.
- **Citations:** Mandatory for all factual claims. Agent outputs MUST cite `evidence_chunk_ids` from retrieval. The Critic agent and Pydantic validation (min_length=1) enforce this.
- **Structured Output:** All agent responses must be validated against Pydantic schemas. Use the `AgentRunner` with its JSON repair loop for reliable outputs.
- **Council Debate:** Use the Council of LLMs (Anthropic, Gemini, OpenAI, etc.) for hallucination defense and vendor diversity. Synthesis is performed by a designated judge.

## Technical Standards

- **Python:** 3.10+, type hints required.
- **Linting/Formatting:** `ruff` and `black` (100 characters line length).
- **Type Checking:** `mypy` --strict.
- **Testing:** `pytest` with `pytest-asyncio`. Aim for high coverage; use existing tests as templates.
- **Hardware Safety:**
    - Always check `nvidia-smi` before recommending LLM tiers or running heavy inference.
    - DO NOT restart system services on the shared lab server.
    - DO NOT use `sudo` without explicit flagging and reason.

## Project Structure

- `src/bizpulse/agents/`: LangGraph nodes, Council logic, AgentRunner.
- `src/bizpulse/retrieval/`: Qdrant integration, hybrid search, reranking.
- `src/bizpulse/models/`: Single source of truth for Pydantic schemas.
- `src/bizpulse/api/`: FastAPI endpoints.
- `industries/`: Industry-specific YAML knowledge packs.

## Workflow Rules

- **Research First:** Always check `CLAUDE.md` and `bizpulse_project_conversation.md` for architectural context before implementing new features.
- **No Premature Abstraction:** Prefer repeating code slightly over complex abstractions if it stays within the current build phase.
- **No Fabricated Competitors:** Competitor Scout must verify existence via web search.

## Subdirectory Instructions

- [Agents](./src/bizpulse/agents/AGY.md)
- [Retrieval](./src/bizpulse/retrieval/AGY.md)
- [Models](./src/bizpulse/models/AGY.md)
