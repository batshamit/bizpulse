"""Ingestion-pipeline I/O models: raw artifacts, chunks, embedded chunks."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import Field, field_validator, model_validator

from bizpulse.models.common import (
    BusinessId,
    ChunkId,
    StrictModel,
    TenantId,
    utcnow,
)

# Where a chunk came from. Drives retrieval re-ranking and per-source-type
# weighting in the industry pack.
SourceType = Literal[
    "website_page",
    "pricing_page",
    "about_page",
    "blog_post",
    "case_study",
    "testimonial",
    "social_post",
    "screenshot_ocr",
    "competitor_page",
]


class RawArtifact(StrictModel):
    """One unit of crawled material before chunking."""

    tenant_id: TenantId
    business_id: BusinessId
    source_url: str = Field(min_length=4)
    source_type: SourceType
    fetched_at: datetime = Field(default_factory=utcnow)
    content_hash: Annotated[str, Field(min_length=8)]
    raw_html: str | None = Field(default=None, description="Optional raw HTML.")
    extracted_text: str = Field(min_length=1, description="Cleaned text used for chunking.")
    screenshot_path: str | None = Field(
        default=None, description="Optional path to a full-page PNG."
    )

    @classmethod
    def hash_text(cls, s: str) -> str:
        return hashlib.sha256(s.encode("utf-8")).hexdigest()[:32]


class ChunkMetadata(StrictModel):
    """Per-chunk metadata — what we filter on at retrieval time.

    `tenant_id` is non-optional. Skipping it in a Qdrant query is a bug; the
    retrieval helper must always include it in the filter.
    """

    tenant_id: TenantId
    business_id: BusinessId
    industry: str | None = None
    source_url: str = Field(min_length=4)
    source_type: SourceType
    section: str | None = Field(default=None, description="Hero/Pricing/About/...")
    parent_chunk_id: ChunkId | None = Field(
        default=None,
        description="If set, retrieval returns the larger parent chunk for context.",
    )
    crawled_at: datetime = Field(default_factory=utcnow)
    content_hash: Annotated[str, Field(min_length=8)]


class Chunk(StrictModel):
    """A unit of text the retriever indexes."""

    id: ChunkId = Field(default_factory=uuid4)
    text: str = Field(min_length=1)
    metadata: ChunkMetadata

    @field_validator("text")
    @classmethod
    def _text_not_too_long(cls, v: str) -> str:
        # Hard cap at ~8000 chars; bge-large-en context is 512 tokens (~2000
        # chars) — anything bigger is almost certainly a chunker bug.
        if len(v) > 8000:
            raise ValueError(f"chunk text too long: {len(v)} chars (cap 8000)")
        return v


class EmbeddedChunk(StrictModel):
    """A chunk after embedding. Vector dim must match `embed_dim`."""

    chunk: Chunk
    vector: list[float] = Field(min_length=1)
    embed_model: str = Field(min_length=1)
    embed_dim: int = Field(gt=0)

    @model_validator(mode="after")
    def _dim_matches(self) -> EmbeddedChunk:
        if len(self.vector) != self.embed_dim:
            raise ValueError(
                f"embedding dim mismatch: vector has {len(self.vector)}, "
                f"declared embed_dim={self.embed_dim}"
            )
        return self
