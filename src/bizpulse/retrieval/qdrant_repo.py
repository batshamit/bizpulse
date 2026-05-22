"""Tenant-isolated Qdrant repository.

This module is the ONLY place outside `qdrant_client` that should touch the
vector store. Every public method enforces a per-tenant `MatchValue` filter
on `tenant_id` — bypassing this class is how data leaks happen.

Backends:
- Embedded mode (`QDRANT_URL=embedded:./data/qdrant`) — for local dev / tests.
  Uses `qdrant_client.QdrantClient(path=...)`.
- HTTP mode (default `QDRANT_URL=http://127.0.0.1:6333`) — production / demo.

Collection naming: `bizpulse_<tenant_id>`. One collection per tenant gives us
both isolation (no cross-tenant queries possible) and tenancy-level snapshots.
The redundant payload filter is belt-and-suspenders for an audit/log trail.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PointStruct,
    VectorParams,
)

from bizpulse.config import settings
from bizpulse.logging import get_logger
from bizpulse.models.common import TenantId
from bizpulse.models.ingest import EmbeddedChunk, SourceType
from bizpulse.models.retrieval import RetrievalMethod, RetrievedChunk

log = get_logger(__name__)

_EMBEDDED_PREFIX = "embedded:"


def _make_client(url: str | None = None) -> QdrantClient:
    target = (url or settings.qdrant_url).strip()
    if target.startswith(_EMBEDDED_PREFIX):
        path = target.removeprefix(_EMBEDDED_PREFIX) or "./data/qdrant"
        return QdrantClient(path=path)
    return QdrantClient(url=target, api_key=settings.qdrant_api_key)


class TenantQdrant:
    """Repository scoped to one tenant. Construct once per tenant per request."""

    def __init__(self, tenant_id: TenantId, client: QdrantClient | None = None) -> None:
        self.tenant_id = tenant_id
        self._client = client or _make_client()
        self.collection = f"bizpulse_{tenant_id}"

    # ---------- lifecycle --------------------------------------------------

    def ensure_collection(self, vector_size: int, distance: Distance = Distance.COSINE) -> None:
        existing = {c.name for c in self._client.get_collections().collections}
        if self.collection in existing:
            return
        self._client.create_collection(
            collection_name=self.collection,
            vectors_config=VectorParams(size=vector_size, distance=distance),
        )
        log.info(
            "qdrant.collection.created",
            tenant=str(self.tenant_id),
            collection=self.collection,
            dim=vector_size,
        )

    def close(self) -> None:
        self._client.close()

    # ---------- writes -----------------------------------------------------

    def upsert(self, embedded: list[EmbeddedChunk]) -> int:
        """Upsert chunks. Each chunk's metadata.tenant_id MUST match self.tenant_id."""
        if not embedded:
            return 0

        for ec in embedded:
            if ec.chunk.metadata.tenant_id != self.tenant_id:
                raise ValueError(
                    f"tenant mismatch on upsert: chunk={ec.chunk.metadata.tenant_id} "
                    f"!= repo={self.tenant_id}"
                )

        points = [
            PointStruct(
                id=str(ec.chunk.id),
                vector=ec.vector,
                payload={
                    "tenant_id": str(ec.chunk.metadata.tenant_id),
                    "business_id": str(ec.chunk.metadata.business_id),
                    "industry": ec.chunk.metadata.industry,
                    "source_url": ec.chunk.metadata.source_url,
                    "source_type": ec.chunk.metadata.source_type,
                    "section": ec.chunk.metadata.section,
                    "content_hash": ec.chunk.metadata.content_hash,
                    "text": ec.chunk.text,
                },
            )
            for ec in embedded
        ]
        self._client.upsert(collection_name=self.collection, points=points)
        log.info("qdrant.upsert", tenant=str(self.tenant_id), count=len(points))
        return len(points)

    # ---------- reads ------------------------------------------------------

    def search(
        self,
        query_vector: list[float],
        *,
        top_k: int = 10,
        business_id: UUID | None = None,
        industry: str | None = None,
        source_types: list[SourceType] | None = None,
        method: RetrievalMethod = "dense",
    ) -> list[RetrievedChunk]:
        """Search inside this tenant's collection.

        Filter ALWAYS includes tenant_id. Additional filters are AND-ed.
        """
        must: list[Any] = [
            FieldCondition(
                key="tenant_id",
                match=MatchValue(value=str(self.tenant_id)),
            ),
        ]
        if business_id is not None:
            must.append(FieldCondition(key="business_id", match=MatchValue(value=str(business_id))))
        if industry is not None:
            must.append(FieldCondition(key="industry", match=MatchValue(value=industry)))
        if source_types:
            must.append(FieldCondition(key="source_type", match=MatchAny(any=[str(s) for s in source_types])))

        flt = Filter(must=must)
        # `query_points` is the modern API (replaces deprecated `search`).
        resp = self._client.query_points(
            collection_name=self.collection,
            query=query_vector,
            limit=top_k,
            query_filter=flt,
            with_payload=True,
        )

        hits: list[RetrievedChunk] = []
        for rank, p in enumerate(resp.points):
            payload = p.payload or {}
            hits.append(
                _hit_to_retrieved_chunk(
                    rank=rank,
                    chunk_id=p.id,
                    score=float(p.score or 0.0),
                    payload=payload,
                    method=method,
                )
            )
        return hits


def _hit_to_retrieved_chunk(
    *,
    rank: int,
    chunk_id: Any,
    score: float,
    payload: dict[str, Any],
    method: RetrievalMethod,
) -> RetrievedChunk:
    from bizpulse.models.ingest import Chunk, ChunkMetadata

    meta = ChunkMetadata(
        tenant_id=payload["tenant_id"],
        business_id=payload["business_id"],
        industry=payload.get("industry"),
        source_url=payload["source_url"],
        source_type=payload["source_type"],
        section=payload.get("section"),
        content_hash=payload["content_hash"],
    )
    chunk = Chunk(
        id=UUID(str(chunk_id)) if not isinstance(chunk_id, UUID) else chunk_id,
        text=payload.get("text", ""),
        metadata=meta,
    )
    return RetrievedChunk(
        chunk=chunk,
        score=max(0.0, min(1.0, score)),
        rank=rank,
        method=method,
    )
