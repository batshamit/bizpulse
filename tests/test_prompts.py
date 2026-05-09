"""Tests for the PromptBuilder — industry injection + citation contract."""

from __future__ import annotations

from uuid import uuid4

import pytest

from bizpulse.agents import PromptBuilder
from bizpulse.models import (
    Chunk,
    ChunkMetadata,
    RetrievedChunk,
    load_industry,
)


def _retrieved(text: str, score: float = 0.9, section: str | None = None) -> RetrievedChunk:
    meta = ChunkMetadata(
        tenant_id=uuid4(),
        business_id=uuid4(),
        industry="fintech",
        source_url="https://example.com/about",
        source_type="about_page",
        section=section,
        content_hash="0" * 32,
    )
    return RetrievedChunk(
        chunk=Chunk(text=text, metadata=meta),
        score=score,
        rank=0,
        method="reranked",
    )


def test_system_prompt_mentions_role_and_citation_rule() -> None:
    pb = PromptBuilder()
    sys = pb.system_prompt("strategist")
    assert "synthesize" in sys.lower()
    assert "citations" in sys.lower() or "evidence_chunk_ids" in sys.lower()


def test_system_prompt_unknown_agent_rejected() -> None:
    pb = PromptBuilder()
    with pytest.raises(ValueError):
        pb.system_prompt("not-a-real-agent")  # type: ignore[arg-type]


def test_industry_pack_injected_into_system_prompt() -> None:
    pack = load_industry("fintech")
    pb = PromptBuilder(industry_pack=pack)
    sys = pb.system_prompt("brand_analyst")
    # Industry name AND a regulation OR competitor seed should appear.
    assert "Financial Technology" in sys
    assert "fintech" in sys.lower()
    # Regulation example from fintech.yaml — RBI lending guidelines
    assert "RBI" in sys
    # The prompt_addendum is included
    assert "regulated financial services" in sys.lower()


def test_real_estate_addendum_distinct_from_fintech() -> None:
    re_pack = load_industry("real_estate")
    fin_pack = load_industry("fintech")
    sys_re = PromptBuilder(industry_pack=re_pack).system_prompt("strategist")
    sys_fin = PromptBuilder(industry_pack=fin_pack).system_prompt("strategist")
    assert "RERA" in sys_re
    assert "RERA" not in sys_fin
    assert sys_re != sys_fin


def test_user_prompt_lists_chunks_with_ids() -> None:
    pb = PromptBuilder()
    chunks = [
        _retrieved("We help fintech startups stay RBI-compliant.", section="About"),
        _retrieved("Three pricing tiers.", score=0.7),
    ]
    user = pb.user_prompt(
        task="Extract brand positioning",
        context_chunks=chunks,
        output_schema_name="BrandAnalysis",
    )
    assert "BrandAnalysis" in user
    # Both chunk IDs are referenced
    for rc in chunks:
        assert f"chunk:{rc.chunk.id}" in user
    assert "section=About" in user


def test_user_prompt_handles_empty_context() -> None:
    pb = PromptBuilder()
    user = pb.user_prompt("task", context_chunks=[], output_schema_name="BrandAnalysis")
    assert "no context" in user.lower()


def test_build_returns_pair() -> None:
    pb = PromptBuilder()
    sys, user = pb.build("brand_analyst", "task", [], "BrandAnalysis")
    assert sys
    assert user
    assert sys != user
