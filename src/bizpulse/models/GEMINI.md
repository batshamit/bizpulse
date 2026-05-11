# Models Module Instructions

This module contains the Pydantic schemas that serve as the single source of truth for the project.

## Schema Standards

- **StrictModel:** Most models inherit from `StrictModel` (defined in `common.py`) which enforces `extra="forbid"`.
- **Citations:** Factual claims must include a `citations` list or `evidence_chunk_ids`.
- **Validation:** Use `min_length=1` on lists that require evidence (like recommendations or value propositions).

## Lenient UUID Parsing

- **Hallucination Resilience:** Models use `_coerce_chunk_id` (from `citations.py`) to handle truncated or fabricated UUIDs from LLMs. This maps bad IDs to an `_UNKNOWN_CHUNK` sentinel instead of failing validation.
- **Critic Role:** The sentinel allows the strategy to be valid for the UI/debug loop while enabling the Critic agent to flag ungrounded claims later.

## Structure

- `strategy.py`: Final `MarketingStrategy` and its sub-analyses (Brand, Audience, Competitor, Content).
- `common.py`: Base classes and shared ID types (TenantId, BusinessId).
- `ingest.py`: Chunks and ingestion-specific models.
