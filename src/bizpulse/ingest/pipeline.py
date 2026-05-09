"""Ingestion orchestrator — composes chunker → embedder → Qdrant upsert.

This is the entry point used by the API/MCP "analyze_business" tool. It takes
a stream of `RawArtifact`s (from the crawler) and persists them as searchable
chunks under the tenant's Qdrant collection.

Embedder is injected so tests can supply a fake without touching TEI.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from bizpulse.ingest.chunker import chunk_artifact
from bizpulse.logging import get_logger
from bizpulse.models.ingest import Chunk, EmbeddedChunk, RawArtifact
from bizpulse.retrieval.qdrant_repo import TenantQdrant

log = get_logger(__name__)


class EmbedderProtocol(Protocol):
    """Anything that can turn a list of texts into a list of vectors."""

    embed_dim: int
    model: str

    async def embed(self, texts: list[str]) -> list[list[float]]:  # pragma: no cover - protocol
        ...


class IngestionPipeline:
    """Run the chunk → embed → upsert sequence for one business.

    Construct once per tenant; reuse across multiple `ingest()` calls.
    """

    def __init__(
        self,
        repo: TenantQdrant,
        embedder: EmbedderProtocol,
        *,
        industry: str | None = None,
        batch_size: int = 32,
    ) -> None:
        self.repo = repo
        self.embedder = embedder
        self.industry = industry
        self.batch_size = batch_size

    async def ingest(self, artifacts: Iterable[RawArtifact]) -> int:
        """Process artifacts and return the count of chunks persisted."""
        # 1. Chunk every artifact.
        chunks: list[Chunk] = []
        for art in artifacts:
            if art.tenant_id != self.repo.tenant_id:
                raise ValueError(
                    f"tenant mismatch on ingest: artifact={art.tenant_id} "
                    f"!= repo={self.repo.tenant_id}"
                )
            chunks.extend(chunk_artifact(art, industry=self.industry))

        if not chunks:
            log.info("ingest.empty", tenant=str(self.repo.tenant_id))
            return 0

        # 2. Ensure collection at the embedder's dim.
        self.repo.ensure_collection(vector_size=self.embedder.embed_dim)

        # 3. Embed in batches and upsert as we go (lower peak memory).
        total = 0
        for start in range(0, len(chunks), self.batch_size):
            batch = chunks[start : start + self.batch_size]
            texts = [c.text for c in batch]
            vectors = await self.embedder.embed(texts)
            if len(vectors) != len(batch):
                raise RuntimeError(
                    f"embedder returned {len(vectors)} vectors for {len(batch)} texts"
                )
            embedded = [
                EmbeddedChunk(
                    chunk=chunk,
                    vector=vec,
                    embed_model=self.embedder.model,
                    embed_dim=self.embedder.embed_dim,
                )
                for chunk, vec in zip(batch, vectors, strict=True)
            ]
            total += self.repo.upsert(embedded)

        log.info(
            "ingest.complete",
            tenant=str(self.repo.tenant_id),
            chunks=total,
            artifacts=sum(1 for _ in []),  # placeholder; caller knows
        )
        return total
