"""RetrievalEngine — the one helper every agent calls to fetch context.

Pipeline per query:
  1. Embed query text with TEI.
  2. Search the tenant's Qdrant collection (filter on tenant_id is mandatory).
  3. (optional) Rerank top-K' candidates with the cross-encoder, return top-K.

Rules baked in here:
  - tenant_id is REQUIRED on the query — it's not allowed to be None or '*'.
    Every retrieval is per-tenant. Pass tenant_id explicitly even for
    single-tenant deploys.
  - if `query.rerank=True` and a reranker is available, we fetch
    `rerank_oversample × top_k` from Qdrant, rerank, then return top_k.
  - the returned RetrievalResult.method reflects what actually happened
    ('reranked' if the rerank step ran successfully, 'dense' otherwise).
"""

from __future__ import annotations

import time

from bizpulse.logging import get_logger
from bizpulse.models.retrieval import (
    RetrievalMethod,
    RetrievalQuery,
    RetrievalResult,
    RetrievedChunk,
)
from bizpulse.retrieval.embeddings import TEIEmbedder, TEIError, TEIReranker
from bizpulse.retrieval.qdrant_repo import TenantQdrant

log = get_logger(__name__)


class RetrievalEngine:
    """Bind a tenant repo + embedder + (optional) reranker; call `.search()`.

    All three collaborators are injected so tests can substitute fakes.
    """

    def __init__(
        self,
        repo: TenantQdrant,
        embedder: TEIEmbedder,
        reranker: TEIReranker | None = None,
        *,
        rerank_oversample: int = 4,
    ) -> None:
        if rerank_oversample < 1:
            raise ValueError("rerank_oversample must be >= 1")
        self.repo = repo
        self.embedder = embedder
        self.reranker = reranker
        self.rerank_oversample = rerank_oversample

    async def search(self, query: RetrievalQuery) -> RetrievalResult:
        if query.tenant_id != self.repo.tenant_id:
            raise ValueError(
                f"tenant mismatch: query={query.tenant_id} != repo={self.repo.tenant_id}"
            )

        t0 = time.perf_counter()

        # 1. Embed query.
        vectors = await self.embedder.embed([query.text])
        if not vectors:
            return RetrievalResult(query=query, chunks=[], latency_ms=0.0, method="dense")
        qvec = vectors[0]

        # 2. Dense search. Oversample if we'll rerank.
        want_rerank = query.rerank and self.reranker is not None
        fetch_k = query.top_k * self.rerank_oversample if want_rerank else query.top_k
        candidates = self.repo.search(
            query_vector=qvec,
            top_k=fetch_k,
            business_id=query.business_id,
            industry=query.industry,
            source_types=query.source_types,
            method="dense",
        )

        method: RetrievalMethod = "dense"
        chunks = candidates

        # 3. Rerank. Failure here falls back to the dense ordering — agents
        #    must still get *some* context even if the reranker is down.
        if want_rerank and candidates:
            try:
                pairs = await self.reranker.rerank(  # type: ignore[union-attr]
                    query=query.text,
                    texts=[c.chunk.text for c in candidates],
                    top_n=query.top_k,
                )
                reranked: list[RetrievedChunk] = []
                for new_rank, (orig_idx, score) in enumerate(pairs):
                    rc = candidates[orig_idx]
                    reranked.append(
                        RetrievedChunk(
                            chunk=rc.chunk,
                            score=max(0.0, min(1.0, float(score))),
                            rank=new_rank,
                            method="reranked",
                        )
                    )
                chunks = reranked
                method = "reranked"
            except TEIError as exc:
                log.warning(
                    "retrieval.rerank_failed_fallback_to_dense",
                    tenant=str(self.repo.tenant_id),
                    error=str(exc)[:200],
                )
                # keep `chunks = candidates` and `method = "dense"`.
                chunks = candidates[: query.top_k]

        latency_ms = (time.perf_counter() - t0) * 1000.0
        return RetrievalResult(query=query, chunks=chunks, latency_ms=latency_ms, method=method)
