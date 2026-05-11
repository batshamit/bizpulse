# Agents Module Instructions

This module handles the multi-agent debate and reasoning logic.

## Key Components

- **Council (`council.py`):** Implements the N-round debate pattern. Round 1 is independent, subsequent rounds are peer-revisions, followed by synthesis.
- **AgentRunner (`runner.py`):** Orchestrates the retrieval -> debate -> parse -> repair lifecycle. Use this for all analytical agents.
- **Nodes (`nodes.py`):** LangGraph node factories. They capture the runner and return async functions that update the `AnalysisState`.

## Implementation Rules

- **Debate Pattern:** Stick to the established Council rounds. Avoid adding extra rounds unless requested, as it increases latency and cost.
- **JSON Repair:** `AgentRunner` perform ONE repair attempt by re-prompting the judge with the validation error. Do not manually implement repair logic in agents.
- **Citations:** Agents MUST cite `chunk_id`s. The `MarketingStrategy` and related models enforce this via `min_length=1` on citation fields.
- **Node Failure:** Nodes should NOT raise exceptions. Instead, record the error in `state["errors"]` and leave the corresponding analysis slot as `None`. The Strategist is designed to degrade gracefully.
- **Compact Summary:** The Strategist node (`make_strategist_node`) uses a compact summary of prior agent outputs (`_summarize_prior_compact`) to fit within vendor token limits (e.g., Groq's 12K ceiling).

## LLM Tiering

- **Judge:** Use strong models (Claude 3.5 Sonnet, GPT-4o) for synthesis and repair.
- **Members:** Mix vendors (Anthropic, Gemini, OpenAI, Perplexity, DeepSeek) to ensure diversity and resilience.
