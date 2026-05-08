"""Retrieval-layer I/O — what the multi-tenant search returns to agents."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from bizpulse.models.common import BusinessId, StrictModel, TenantId
from bizpulse.models.ingest import Chunk, SourceType

RetrievalMethod = Literal["dense", "bm25", "hybrid", "reranked"]


class RetrievalQuery(StrictModel):
    """One retrieval call. The retriever MUST filter by tenant_id."""

    text: str = Field(min_length=1)
    tenant_id: TenantId
    business_id: BusinessId | None = Field(
        default=None,
        description="If set, restrict to a single business within the tenant.",
    )
    industry: str | None = None
    source_types: list[SourceType] | None = Field(
        default=None,
        description="Optional whitelist; None means all source types.",
    )
    top_k: int = Field(default=10, ge=1, le=200)
    rerank: bool = True


class RetrievedChunk(StrictModel):
    """A chunk returned by retrieval with score + rank metadata."""

    chunk: Chunk
    score: float = Field(ge=0.0, le=1.0)
    rank: int = Field(ge=0)
    method: RetrievalMethod


class RetrievalResult(StrictModel):
    """Bundle of retrieved chunks with the query and timing."""

    query: RetrievalQuery
    chunks: list[RetrievedChunk] = Field(default_factory=list)
    latency_ms: float = Field(ge=0.0)
    method: RetrievalMethod
