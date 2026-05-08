"""Citations — the ground-truth link between every claim and its source chunk."""

from __future__ import annotations

from pydantic import Field

from bizpulse.models.common import ChunkId, StrictModel


class Citation(StrictModel):
    """One claim ↔ one chunk. The Critic agent traverses these to verify
    every assertion is grounded in retrieval.
    """

    chunk_id: ChunkId
    quote: str | None = Field(
        default=None,
        description="Optional exact span from the chunk that supports the claim.",
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
