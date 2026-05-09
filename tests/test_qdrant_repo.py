"""Tests for the tenant-isolated Qdrant repository (embedded mode)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from qdrant_client import QdrantClient

from bizpulse.models import (
    Chunk,
    ChunkMetadata,
    EmbeddedChunk,
)
from bizpulse.retrieval import TenantQdrant


@pytest.fixture
def repo(tmp_path: Path) -> TenantQdrant:
    """Fresh embedded Qdrant per test to avoid cross-test bleed."""
    tenant = uuid4()
    client = QdrantClient(path=str(tmp_path / "qdrant"))
    repo = TenantQdrant(tenant, client=client)
    repo.ensure_collection(vector_size=4)
    yield repo
    repo.close()


def _embedded(repo: TenantQdrant, text: str, vec: list[float], industry: str = "fintech") -> EmbeddedChunk:
    meta = ChunkMetadata(
        tenant_id=repo.tenant_id,
        business_id=uuid4(),
        industry=industry,
        source_url="https://example.com/x",
        source_type="about_page",
        content_hash="abcdef0123456789",
    )
    return EmbeddedChunk(
        chunk=Chunk(text=text, metadata=meta),
        vector=vec,
        embed_model="bge-large-en-v1.5",
        embed_dim=4,
    )


def test_upsert_and_search_roundtrip(repo: TenantQdrant) -> None:
    a = _embedded(repo, "alpha", [1.0, 0.0, 0.0, 0.0])
    b = _embedded(repo, "beta",  [0.0, 1.0, 0.0, 0.0])
    repo.upsert([a, b])

    hits = repo.search([1.0, 0.0, 0.0, 0.0], top_k=2)
    assert len(hits) == 2
    assert hits[0].chunk.text == "alpha"
    assert hits[0].score >= hits[1].score


def test_upsert_rejects_other_tenant(repo: TenantQdrant) -> None:
    other = uuid4()
    meta = ChunkMetadata(
        tenant_id=other,
        business_id=uuid4(),
        source_url="https://example.com/x",
        source_type="about_page",
        content_hash="abcdef0123456789",
    )
    bad = EmbeddedChunk(
        chunk=Chunk(text="cross-tenant payload", metadata=meta),
        vector=[1.0, 0.0, 0.0, 0.0],
        embed_model="bge-large-en-v1.5",
        embed_dim=4,
    )
    with pytest.raises(ValueError, match="tenant mismatch"):
        repo.upsert([bad])


def test_search_returns_only_this_tenant(tmp_path: Path) -> None:
    """Two tenants share a process-wide embedded Qdrant; each has its own
    collection. Searching tenant-A must never surface tenant-B chunks even if
    they happen to live in the same db file."""
    client = QdrantClient(path=str(tmp_path / "qdrant"))
    a = TenantQdrant(uuid4(), client=client)
    b = TenantQdrant(uuid4(), client=client)
    a.ensure_collection(vector_size=4)
    b.ensure_collection(vector_size=4)

    a.upsert([_embedded(a, "alpha-secret", [1.0, 0.0, 0.0, 0.0])])
    b.upsert([_embedded(b, "beta-secret",  [1.0, 0.0, 0.0, 0.0])])

    a_hits = a.search([1.0, 0.0, 0.0, 0.0], top_k=10)
    assert all(h.chunk.text == "alpha-secret" for h in a_hits)

    b_hits = b.search([1.0, 0.0, 0.0, 0.0], top_k=10)
    assert all(h.chunk.text == "beta-secret" for h in b_hits)
    a.close()
    b.close()


def test_industry_filter(repo: TenantQdrant) -> None:
    repo.upsert([
        _embedded(repo, "fin-1", [1.0, 0.0, 0.0, 0.0], industry="fintech"),
        _embedded(repo, "re-1",  [1.0, 0.0, 0.0, 0.0], industry="real_estate"),
    ])
    hits = repo.search([1.0, 0.0, 0.0, 0.0], top_k=10, industry="fintech")
    assert all(h.chunk.metadata.industry == "fintech" for h in hits)
    assert any(h.chunk.text == "fin-1" for h in hits)
