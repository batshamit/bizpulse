"""Tests for ingestion-pipeline models: chunks, embeddings, retrieval queries."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from bizpulse.models import (
    Chunk,
    ChunkMetadata,
    EmbeddedChunk,
    RawArtifact,
    RetrievalQuery,
)


def _meta() -> ChunkMetadata:
    return ChunkMetadata(
        tenant_id=uuid4(),
        business_id=uuid4(),
        source_url="https://example.com/about",
        source_type="about_page",
        content_hash="0" * 32,
    )


def test_chunk_text_too_long_rejected() -> None:
    with pytest.raises(ValidationError):
        Chunk(text="x" * 8001, metadata=_meta())


def test_chunk_round_trip() -> None:
    c = Chunk(text="We process payments for gig workers.", metadata=_meta())
    blob = c.model_dump_json()
    c2 = Chunk.model_validate_json(blob)
    assert c2.id == c.id
    assert c2.text == c.text


def test_embedded_chunk_dim_mismatch_rejected() -> None:
    chunk = Chunk(text="hello", metadata=_meta())
    with pytest.raises(ValidationError):
        EmbeddedChunk(
            chunk=chunk,
            vector=[0.1, 0.2, 0.3],   # 3 dims
            embed_model="bge-large-en-v1.5",
            embed_dim=1024,           # claimed 1024 → mismatch
        )


def test_raw_artifact_hash_helper() -> None:
    text = "hello world"
    h = RawArtifact.hash_text(text)
    assert len(h) == 32
    assert h == RawArtifact.hash_text(text)  # deterministic


def test_retrieval_query_clamps_top_k() -> None:
    with pytest.raises(ValidationError):
        RetrievalQuery(
            text="positioning",
            tenant_id=uuid4(),
            top_k=0,    # below minimum
        )
    with pytest.raises(ValidationError):
        RetrievalQuery(
            text="positioning",
            tenant_id=uuid4(),
            top_k=500,  # above maximum
        )

    ok = RetrievalQuery(text="positioning", tenant_id=uuid4(), top_k=15)
    assert ok.top_k == 15
    assert ok.rerank is True
