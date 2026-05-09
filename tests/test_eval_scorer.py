"""Unit tests for the scorer (no LLM, no Qdrant)."""

from __future__ import annotations

from uuid import uuid4

from pydantic import BaseModel

from bizpulse.agents.runner import AgentRunResult
from bizpulse.agents.council import CouncilResult
from bizpulse.eval.golden import TaskExpectation
from bizpulse.eval.scorer import (
    extract_cited_chunk_ids,
    extract_confidence,
    score_task,
)
from bizpulse.models import (
    BrandAnalysis,
    Citation,
    Recommendation,
)


class _Toy(BaseModel):
    summary: str
    confidence: float


def _make_council_result(cost: float = 0.001, latency: float = 100.0) -> CouncilResult:
    return CouncilResult(
        final="{}",
        judge="fake",
        cost_usd=cost,
        latency_ms=latency,
    )


def test_extract_cited_chunk_ids_brand_analysis() -> None:
    cid_a, cid_b = uuid4(), uuid4()
    out = BrandAnalysis(
        positioning="x",
        tone="x",
        value_props=["a"],
        citations=[
            Citation(chunk_id=cid_a, quote="q1"),
            Citation(chunk_id=cid_b, quote="q2"),
        ],
    )
    found = extract_cited_chunk_ids(out)
    assert {str(cid_a), str(cid_b)} == found


def test_extract_cited_chunk_ids_recommendation_evidence() -> None:
    cid_a, cid_b = uuid4(), uuid4()
    rec = Recommendation(
        channel="linkedin",
        action="post",
        rationale="r",
        evidence_chunk_ids=[cid_a, cid_b],
        confidence=0.8,
    )
    found = extract_cited_chunk_ids(rec)
    assert {str(cid_a), str(cid_b)} == found


def test_extract_confidence() -> None:
    assert extract_confidence(_Toy(summary="x", confidence=0.7)) == 0.7


def test_score_passes_happy_path() -> None:
    cid = uuid4()
    out = BrandAnalysis(
        positioning="compliance-first neobank for gig workers",
        tone="trustworthy",
        value_props=["full-KYC"],
        citations=[Citation(chunk_id=cid, quote="q")],
    )
    result = AgentRunResult(
        agent="brand_analyst",
        output=out,
        council=_make_council_result(),
        repair_attempted=False,
        latency_ms=120.0,
    )
    expected = TaskExpectation(
        min_citations=1,
        must_contain_keywords=["gig", "compliance"],
        must_not_contain_keywords=["crypto"],
    )
    s = score_task(task_id="t1", result=result, expected=expected)
    assert s.passed is True
    assert s.citation_count == 1
    assert all(s.keyword_hits.values())
    assert not any(s.forbidden_hits.values())


def test_score_fails_on_forbidden_keyword() -> None:
    cid = uuid4()
    out = BrandAnalysis(
        positioning="we accept BTC and Ethereum",
        tone="bullish",
        value_props=["crypto-native banking"],
        citations=[Citation(chunk_id=cid, quote="q")],
    )
    result = AgentRunResult(
        agent="brand_analyst",
        output=out,
        council=_make_council_result(),
        repair_attempted=False,
        latency_ms=10.0,
    )
    expected = TaskExpectation(must_not_contain_keywords=["crypto", "BTC"])
    s = score_task(task_id="t1", result=result, expected=expected)
    assert s.passed is False
    assert any(s.forbidden_hits.values())


def test_score_fails_on_too_few_citations() -> None:
    out = BrandAnalysis(
        positioning="x", tone="x", value_props=["a"],
        citations=[Citation(chunk_id=uuid4())],
    )
    result = AgentRunResult(
        agent="brand_analyst",
        output=out,
        council=_make_council_result(),
        repair_attempted=False,
        latency_ms=1.0,
    )
    expected = TaskExpectation(min_citations=3)
    assert score_task(task_id="t1", result=result, expected=expected).passed is False


def test_score_fails_on_latency_budget() -> None:
    out = BrandAnalysis(
        positioning="x", tone="x", value_props=["a"],
        citations=[Citation(chunk_id=uuid4())],
    )
    result = AgentRunResult(
        agent="brand_analyst",
        output=out,
        council=_make_council_result(),
        repair_attempted=False,
        latency_ms=10_000.0,
    )
    expected = TaskExpectation(max_latency_ms=1000.0)
    assert score_task(task_id="t1", result=result, expected=expected).passed is False
