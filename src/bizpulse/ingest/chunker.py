"""Section-aware semantic chunker.

Takes a `RawArtifact` and emits `Chunk` objects with metadata. The shape of the
chunks is what eventually gets indexed in Qdrant and reranked at query time.

Phase-3 strategy (intentionally simple):
1. Split on blank-line boundaries to find sections / paragraphs.
2. Each section becomes one chunk if it fits within `max_chars`.
3. Larger sections are windowed into target_chars-sized pieces with overlap.
4. Tiny fragments (< min_chars) are dropped — they almost never help retrieval
   and they pollute reranker scores.

Section labels are derived from the first non-blank line of a paragraph if it
"looks like a heading" (short, mostly non-punctuation). Otherwise None.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from bizpulse.models.ingest import Chunk, ChunkMetadata, RawArtifact

_PARAGRAPH_RE = re.compile(r"\n\s*\n+")
_WHITESPACE_RE = re.compile(r"\s+")
_HEADING_PUNCT_RE = re.compile(r"[.!?]")


def _normalize(text: str) -> str:
    """Trim and collapse runs of internal whitespace."""
    return _WHITESPACE_RE.sub(" ", text.strip())


def _looks_like_heading(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 80:
        return False
    if _HEADING_PUNCT_RE.search(s):
        return False
    # mostly capitalized words OR title-case words
    words = s.split()
    if not words:
        return False
    capish = sum(1 for w in words if w[:1].isupper())
    return capish / len(words) >= 0.5


def _split_paragraphs(text: str) -> list[str]:
    return [p for p in _PARAGRAPH_RE.split(text) if p.strip()]


def _window(text: str, target: int, overlap: int) -> Iterable[str]:
    """Yield overlapping windows. Prefers cutting on whitespace."""
    if len(text) <= target:
        yield text
        return
    i = 0
    while i < len(text):
        end = min(i + target, len(text))
        # bias the cut toward a word boundary if we're not at end of text
        if end < len(text):
            # look back up to 60 chars for whitespace
            look_back = 60
            cut = text.rfind(" ", end - look_back, end)
            if cut != -1 and cut > i + target // 2:
                end = cut
        yield text[i:end]
        if end >= len(text):
            break
        i = max(end - overlap, i + 1)


def chunk_artifact(
    artifact: RawArtifact,
    *,
    target_chars: int = 700,
    max_chars: int = 1200,
    min_chars: int = 20,
    overlap: int = 100,
    industry: str | None = None,
) -> list[Chunk]:
    """Chunk one artifact's extracted text. Returns an ordered list."""
    if target_chars >= max_chars:
        raise ValueError("target_chars must be < max_chars")
    if overlap >= target_chars:
        raise ValueError("overlap must be < target_chars")

    base_meta = ChunkMetadata(
        tenant_id=artifact.tenant_id,
        business_id=artifact.business_id,
        industry=industry,
        source_url=artifact.source_url,
        source_type=artifact.source_type,
        content_hash=artifact.content_hash,
    )

    chunks: list[Chunk] = []
    for paragraph in _split_paragraphs(artifact.extracted_text):
        # Try to detect a section label from the first line.
        first_line, _, _rest = paragraph.partition("\n")
        section_label = first_line.strip() if _looks_like_heading(first_line) else None

        body = _normalize(paragraph)
        if len(body) < min_chars:
            continue

        if len(body) <= max_chars:
            meta = base_meta.model_copy(update={"section": section_label})
            chunks.append(Chunk(text=body, metadata=meta))
            continue

        for window in _window(body, target=target_chars, overlap=overlap):
            piece = window.strip()
            if len(piece) < min_chars:
                continue
            meta = base_meta.model_copy(update={"section": section_label})
            chunks.append(Chunk(text=piece, metadata=meta))

    return chunks
