"""Tests for the section-aware chunker."""

from __future__ import annotations

from uuid import uuid4

import pytest

from bizpulse.ingest import chunk_artifact
from bizpulse.models import RawArtifact


def _artifact(text: str, source_type: str = "about_page") -> RawArtifact:
    return RawArtifact(
        tenant_id=uuid4(),
        business_id=uuid4(),
        source_url="https://example.com/about",
        source_type=source_type,  # type: ignore[arg-type]
        content_hash="0" * 32,
        extracted_text=text,
    )


def test_short_text_one_chunk() -> None:
    art = _artifact("We help fintech startups stay RBI-compliant.")
    chunks = chunk_artifact(art)
    assert len(chunks) == 1
    assert chunks[0].metadata.tenant_id == art.tenant_id
    assert chunks[0].metadata.source_type == art.source_type


def test_paragraph_split() -> None:
    text = "First para about the company.\n\nSecond para about pricing tiers.\n\nThird para about contact."
    chunks = chunk_artifact(_artifact(text))
    assert len(chunks) == 3
    assert all(c.metadata.section is None for c in chunks)


def test_heading_detection() -> None:
    text = (
        "About Us\n"
        "We help small lenders meet RBI compliance norms via structured KYC pipelines.\n\n"
        "Pricing\n"
        "Three tiers — starter, growth, enterprise. Pay per active borrower.\n\n"
        "Some long paragraph that has punctuation. Several sentences. "
        "Lots of detail about the company history that wouldn't be a heading."
    )
    chunks = chunk_artifact(_artifact(text))
    sections = [c.metadata.section for c in chunks]
    assert "About Us" in sections
    assert "Pricing" in sections


def test_long_paragraph_windowed() -> None:
    long_para = "lorem ipsum " * 200  # ~2400 chars
    chunks = chunk_artifact(_artifact(long_para), target_chars=400, max_chars=600, overlap=50)
    # Should split into multiple windowed chunks.
    assert len(chunks) >= 4
    for c in chunks:
        assert len(c.text) <= 600  # respects max_chars
    # Adjacent windows should overlap somewhere.
    overlap_seen = any(
        chunks[i].text[-30:] in chunks[i + 1].text or chunks[i + 1].text[:30] in chunks[i].text
        for i in range(len(chunks) - 1)
    )
    assert overlap_seen, "expected overlap between adjacent windows"


def test_tiny_fragments_dropped() -> None:
    text = "Hi.\n\nA very real paragraph that explains positioning at length."
    chunks = chunk_artifact(_artifact(text), min_chars=20)
    assert all(len(c.text) >= 20 for c in chunks)


def test_invalid_overlap_rejected() -> None:
    with pytest.raises(ValueError):
        chunk_artifact(
            _artifact("text"),
            target_chars=100,
            max_chars=200,
            overlap=150,  # >= target
        )
