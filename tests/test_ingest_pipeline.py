"""Tests for the ingestion orchestrator with a fake embedder."""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from qdrant_client import QdrantClient

from bizpulse.ingest import IngestionPipeline
from bizpulse.models import RawArtifact
from bizpulse.retrieval import TenantQdrant


class FakeEmbedder:
    """Deterministic 4-d embedder: hashes text into a small vector."""

    embed_dim = 4
    model = "fake-embed"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            h = hashlib.sha256(t.encode()).digest()
            out.append([h[0] / 255, h[1] / 255, h[2] / 255, h[3] / 255])
        return out


@pytest.fixture
def repo(tmp_path: Path) -> TenantQdrant:
    client = QdrantClient(path=str(tmp_path / "qdrant"))
    repo = TenantQdrant(uuid4(), client=client)
    yield repo
    repo.close()


def _artifact(tenant_id, business_id, text: str) -> RawArtifact:
    return RawArtifact(
        tenant_id=tenant_id,
        business_id=business_id,
        source_url="https://example.com/about",
        source_type="about_page",
        content_hash="0" * 32,
        extracted_text=text,
    )


@pytest.mark.asyncio
async def test_pipeline_chunks_and_upserts(repo: TenantQdrant) -> None:
    bid = uuid4()
    art = _artifact(
        repo.tenant_id,
        bid,
        "We help fintech startups stay RBI-compliant.\n\n"
        "Three pricing tiers — starter, growth, enterprise. Pay per active borrower.\n\n"
        "Contact us at hello@example.com for an onboarding walkthrough.",
    )
    pipe = IngestionPipeline(repo, FakeEmbedder(), industry="fintech")
    n = await pipe.ingest([art])
    assert n >= 2  # at least two paragraphs survive min_chars
    # Round-trip: search returns chunks tagged with the right tenant + industry
    embedder = FakeEmbedder()
    qvec = (await embedder.embed(["pricing"]))[0]
    hits = repo.search(qvec, top_k=5, industry="fintech")
    assert hits
    assert all(h.chunk.metadata.tenant_id == repo.tenant_id for h in hits)
    assert all(h.chunk.metadata.industry == "fintech" for h in hits)


@pytest.mark.asyncio
async def test_pipeline_rejects_other_tenant(repo: TenantQdrant) -> None:
    foreign_tenant = uuid4()
    art = _artifact(foreign_tenant, uuid4(), "some long text that survives min_chars")
    pipe = IngestionPipeline(repo, FakeEmbedder())
    with pytest.raises(ValueError, match="tenant mismatch"):
        await pipe.ingest([art])


@pytest.mark.asyncio
async def test_pipeline_empty_input_safe(repo: TenantQdrant) -> None:
    pipe = IngestionPipeline(repo, FakeEmbedder())
    assert await pipe.ingest([]) == 0


@pytest.mark.asyncio
async def test_pipeline_batches(repo: TenantQdrant) -> None:
    """Verify batching doesn't lose chunks across batch boundaries."""
    bid = uuid4()
    paragraphs = "\n\n".join(
        f"Paragraph number {i} with enough words to clear min_chars threshold cleanly."
        for i in range(50)
    )
    art = _artifact(repo.tenant_id, bid, paragraphs)
    pipe = IngestionPipeline(repo, FakeEmbedder(), batch_size=8)
    n = await pipe.ingest([art])
    assert n >= 50  # one chunk per paragraph
