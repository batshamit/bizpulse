# Retrieval Module Instructions

This module handles vector search, embeddings, and reranking.

## Tenant Isolation (NON-NEGOTIABLE)

- **TenantQdrant (`qdrant_repo.py`):** This is the only place that should interact with Qdrant.
- **Filtering:** Every search MUST include a `MatchValue` filter on `tenant_id`.
- **Validation:** Every upsert MUST verify that the chunk's `tenant_id` matches the repository's `tenant_id`.
- **Collection Naming:** Uses `bizpulse_<tenant_id>`.

## Retrieval Pipeline

- **RetrievalEngine (`search.py`):** The primary entry point for agents.
- **Workflow:** Embed query -> Search Qdrant (filtered) -> (Optional) Rerank top candidates.
- **Fallback:** If the reranker fails, fall back to the dense search results. Never let a reranker outage block the entire agent run.

## Hardware & Performance

- **TEI Clients:** Use `TEIEmbedder` and `TEIReranker` for local GPU-accelerated inference.
- **Latency:** Reranking adds significant latency. Only enable it via `query.rerank=True` when precision is critical.
