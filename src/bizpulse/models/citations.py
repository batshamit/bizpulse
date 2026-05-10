"""Citations — the ground-truth link between every claim and its source chunk."""

from __future__ import annotations

from uuid import UUID

from pydantic import Field, field_validator

from bizpulse.models.common import ChunkId, StrictModel

# Sentinel for "model emitted a chunk_id we can't parse." The Critic agent
# (Phase 12+) flags any citation whose chunk_id is _UNKNOWN_CHUNK as
# ungrounded. We coerce instead of raising so a single bad ID doesn't
# blow up the whole MarketingStrategy validation.
_UNKNOWN_CHUNK = UUID(int=0)


def _coerce_chunk_id(v: object) -> UUID:
    """Lenient UUID parsing for citation chunk_ids.

    Why: LLMs sometimes emit truncated or fabricated chunk IDs even when
    the chunks were presented in full UUID form. Strict UUID validation
    would reject the entire citation list — and with min_length=1 on
    citations across most analytical schemas, that cascades to losing
    the whole agent output. Coercing the bad IDs to a sentinel keeps the
    rest of the structure valid; the Critic agent flags them downstream.
    """
    if isinstance(v, UUID):
        return v
    if isinstance(v, str):
        try:
            return UUID(v)
        except ValueError:
            return _UNKNOWN_CHUNK
    return _UNKNOWN_CHUNK


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

    @field_validator("chunk_id", mode="before")
    @classmethod
    def _lenient_chunk_id(cls, v: object) -> UUID:
        return _coerce_chunk_id(v)
