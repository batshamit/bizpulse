"""Tests for the RetrievalEngine: embed → search → rerank flow."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from qdrant_client import QdrantClient

from bizpulse.models import (
    Chunk,
    ChunkMetadata,
    EmbeddedChunk,
    RetrievalQuery,
)
from bizpulse.retrieval import TEIError, TenantQdrant
from bizpulse.retrieval.embeddings import TEIEmbedder, TEIReranker
from bizpulse.retrieval.search import RetrievalEngine


# --- fakes -------------------------------------------------------------------

class FakeEmbedder:
    embed_dim = 4
    model = "fake"

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        out = []
        for t in texts:
            h = hashlib.sha256(t.encode()).digest()
            out.append([h[0] / 255, h[1] / 255, h[2] / 255, h[3] / 255])
        return out


class FakeReranker:
    """Returns a fixed reordering by index."""

    def __init__(self, ordering: list[int], scores: list[float] | None = None) -> None:
        self.ordering = ordering
        self.scores = scores or [1.0 - 0.1 * i for i in range(len(ordering))]

    async def rerank(self, query: str, texts: list[str], top_n: int | None = None) -> list[tuple[int, float]]:
        pairs = [(i, s) for i, s in zip(self.ordering, self.scores, strict=True)]
        if top_n is not None:
            pairs = pairs[:top_n]
        return pairs


class BrokenReranker:
    async def rerank(self, query: str, texts: list[str], top_n: int | None = None) -> list[tuple[int, float]]:
        raise TEIError("simulated reranker outage")


# --- fixtures ----------------------------------------------------------------

@pytest.fixture
def repo_with_chunks(tmp_path: Path) -> TenantQdrant:
    """Tenant repo seeded with five chunks at distinct vectors."""
    client = QdrantClient(path=str(tmp_path / "qdrant"))
    repo = TenantQdrant(uuid4(), client=client)
    repo.ensure_collection(vector_size=4)

    embedder = FakeEmbedder()
    texts = ["alpha-text", "beta-text", "gamma-text", "delta-text", "epsilon-text"]
    # Run embed synchronously via asyncio in conftest? Simpler: manual hashing.
    embedded: list[EmbeddedChunk] = []
    for t in texts:
        h = hashlib.sha256(t.encode()).digest()
        meta = ChunkMetadata(
            tenant_id=repo.tenant_id,
            business_id=uuid4(),
            source_url="https://example.com/x",
            source_type="about_page",
            content_hash="abcdef0123456789",
        )
        embedded.append(
            EmbeddedChunk(
                chunk=Chunk(text=t, metadata=meta),
                vector=[h[0] / 255, h[1] / 255, h[2] / 255, h[3] / 255],
                embed_model=embedder.model,
                embed_dim=embedder.embed_dim,
            )
        )
    repo.upsert(embedded)
    yield repo
    repo.close()


# --- tests -------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_dense_only(repo_with_chunks: TenantQdrant) -> None:
    eng = RetrievalEngine(repo_with_chunks, embedder=FakeEmbedder())
    q = RetrievalQuery(text="alpha-text", tenant_id=repo_with_chunks.tenant_id, top_k=3, rerank=False)
    res = await eng.search(q)
    assert res.method == "dense"
    assert len(res.chunks) == 3
    assert res.latency_ms >= 0.0


@pytest.mark.asyncio
async def test_search_with_rerank(repo_with_chunks: TenantQdrant) -> None:
    embedder = FakeEmbedder()
    # Ranker reverses Qdrant's natural order. We oversample x2, so 6 candidates,
    # rerank picks ordering [5,4,3,2,1,0] but only 3 are returned (top_k=3).
    rerank = FakeReranker(ordering=[4, 3, 2, 1, 0])
    eng = RetrievalEngine(repo_with_chunks, embedder=embedder, reranker=rerank, rerank_oversample=2)  # type: ignore[arg-type]
    q = RetrievalQuery(text="alpha-text", tenant_id=repo_with_chunks.tenant_id, top_k=3)
    res = await eng.search(q)
    assert res.method == "reranked"
    assert len(res.chunks) == 3
    # ranks should be 0,1,2 in the reranked output
    assert [c.rank for c in res.chunks] == [0, 1, 2]


@pytest.mark.asyncio
async def test_rerank_failure_falls_back_to_dense(repo_with_chunks: TenantQdrant) -> None:
    embedder = FakeEmbedder()
    eng = RetrievalEngine(
        repo_with_chunks,
        embedder=embedder,
        reranker=BrokenReranker(),  # type: ignore[arg-type]
    )
    q = RetrievalQuery(text="alpha-text", tenant_id=repo_with_chunks.tenant_id, top_k=3)
    res = await eng.search(q)
    assert res.method == "dense"
    assert 1 <= len(res.chunks) <= 3


@pytest.mark.asyncio
async def test_tenant_mismatch_rejected(repo_with_chunks: TenantQdrant) -> None:
    eng = RetrievalEngine(repo_with_chunks, embedder=FakeEmbedder())
    other = uuid4()
    q = RetrievalQuery(text="x", tenant_id=other, top_k=3)
    with pytest.raises(ValueError, match="tenant mismatch"):
        await eng.search(q)
