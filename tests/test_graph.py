"""End-to-end test of the LangGraph analysis pipeline against mocked council.

The graph is the actual production wiring — we just feed it a Council whose
members return canned schema-valid JSON. Verifies fan-out + join + final
state shape.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from qdrant_client import QdrantClient

from bizpulse.agents.council import Council
from bizpulse.agents.graph import build_analysis_graph
from bizpulse.agents.runner import AgentRunner
from bizpulse.llm import CallableLLMClient
from bizpulse.models import (
    Chunk,
    ChunkMetadata,
    EmbeddedChunk,
)
from bizpulse.retrieval import TenantQdrant
from bizpulse.retrieval.search import RetrievalEngine


class _Embedder:
    embed_dim = 4
    model = "fake"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.5, 0.5, 0.5, 0.5]] * len(texts)


# Canned outputs — schema-valid for each role's expected output type.
_CHUNK_ID = str(uuid4())

_BRAND_JSON = json.dumps(
    {
        "positioning": "compliance-first neobank",
        "tone": "trustworthy",
        "value_props": ["full-KYC", "instant credit"],
        "citations": [
            {"chunk_id": _CHUNK_ID, "quote": "we are compliance-first", "confidence": 0.9}
        ],
    }
)

_AUDIENCE_JSON = json.dumps(
    {
        "primary": {
            "name": "Gig workers",
            "description": "platform earners 25-35 in tier-1 cities",
            "motivations": ["fast onboarding"],
            "pain_points": ["traditional bank rejection"],
            "citations": [{"chunk_id": _CHUNK_ID, "quote": "gig", "confidence": 0.8}],
        },
        "secondary": [],
        "citations": [{"chunk_id": _CHUNK_ID, "quote": "ICP", "confidence": 0.85}],
    }
)

_COMPETITOR_JSON = json.dumps(
    {
        "competitors": [
            {
                "name": "Jupiter",
                "url": "https://jupiter.money",
                "positioning": "lifestyle neobank",
                "strengths": ["app polish"],
                "weaknesses": ["regulatory posture"],
                "verified": True,
                "citations": [{"chunk_id": _CHUNK_ID, "confidence": 0.7}],
            }
        ],
        "market_position": "late entrant; differentiates on RBI compliance",
        "citations": [{"chunk_id": _CHUNK_ID, "confidence": 0.8}],
    }
)

_CONTENT_JSON = json.dumps(
    {
        "findings": [],
        "pillars_strong": ["regulatory_trust"],
        "pillars_weak": ["financial_literacy"],
        "citations": [],
    }
)

_STRATEGY_JSON = json.dumps(
    {
        "tenant_id": "00000000-0000-0000-0000-000000000001",  # placeholder; node doesn't validate UUID alignment
        "business_id": "00000000-0000-0000-0000-000000000002",
        "industry": "fintech",
        "brand": json.loads(_BRAND_JSON),
        "audience": json.loads(_AUDIENCE_JSON),
        "competitive_landscape": json.loads(_COMPETITOR_JSON),
        "content_audit": json.loads(_CONTENT_JSON),
        "recommendations": [
            {
                "channel": "linkedin",
                "action": "Publish weekly RBI-compliance explainers",
                "rationale": "Audience is regulation-anxious",
                "evidence_chunk_ids": [_CHUNK_ID],
                "confidence": 0.88,
                "priority": "P0",
                "compliance_flags": ["RBI digital lending guidelines"],
            }
        ],
        "overall_confidence": 0.85,
        "summary": "Compliance-first positioning, lean into LinkedIn + WhatsApp.",
    }
)


def _route(_system: str, user: str) -> str:
    """Match the parenthesized schema name PromptBuilder writes once. Order
    matters: the embedded JSON schema for MarketingStrategy contains nested
    type names (BrandAnalysis, AudienceAnalysis, ...), so check the most
    specific superset first."""
    if "(MarketingStrategy)" in user:
        return _STRATEGY_JSON
    if "(BrandAnalysis)" in user:
        return _BRAND_JSON
    if "(AudienceAnalysis)" in user:
        return _AUDIENCE_JSON
    if "(CompetitiveLandscape)" in user:
        return _COMPETITOR_JSON
    if "(ContentAudit)" in user:
        return _CONTENT_JSON
    return "{}"


@pytest.fixture
def runner_with_chunks(tmp_path: Path) -> AgentRunner:
    client = QdrantClient(path=str(tmp_path / "qd"))
    repo = TenantQdrant(uuid4(), client=client)
    repo.ensure_collection(vector_size=4)

    meta = ChunkMetadata(
        tenant_id=repo.tenant_id,
        business_id=uuid4(),
        industry="fintech",
        source_url="https://x.com",
        source_type="about_page",
        content_hash="abcdef0123456789",
    )
    repo.upsert(
        [
            EmbeddedChunk(
                chunk=Chunk(
                    text="we are a compliance-first neobank for gig workers", metadata=meta
                ),
                vector=[1.0, 0.0, 0.0, 0.0],
                embed_model="x",
                embed_dim=4,
            )
        ]
    )
    retrieval = RetrievalEngine(repo, embedder=_Embedder())
    judge = CallableLLMClient(name="judge", vendor="fake", fn=_route)
    member = CallableLLMClient(name="m", vendor="fake", fn=_route)
    council = Council(members=[member], judge=judge, rounds=1)
    return AgentRunner(retrieval=retrieval, council=council, industry="fintech")


@pytest.mark.asyncio
async def test_graph_runs_all_nodes_and_produces_strategy(
    runner_with_chunks: AgentRunner,
) -> None:
    graph = build_analysis_graph(runner_with_chunks)

    initial = {
        "tenant_id": runner_with_chunks.retrieval.repo.tenant_id,
        "business_id": uuid4(),
        "industry": "fintech",
        "business_url": "https://example.test",
    }
    final = await graph.ainvoke(initial)

    # Every analytical slot is populated.
    assert final["brand"] is not None
    assert final["audience"] is not None
    assert final["competitive_landscape"] is not None
    assert final["content_audit"] is not None
    # Strategist ran AFTER the parallel four and produced a final strategy.
    assert final["final_strategy"] is not None
    assert len(final["final_strategy"].recommendations) >= 1
    assert final["final_strategy"].recommendations[0].priority == "P0"


@pytest.mark.asyncio
async def test_graph_continues_when_one_node_fails(
    runner_with_chunks: AgentRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Patch the audience node's runner.run to raise — graph should still
    produce a final_strategy (Strategist sees brand/competitor/content but
    not audience)."""
    from bizpulse.agents.runner import AgentRunError

    real_run = runner_with_chunks.run

    async def maybe_fail(**kw):
        if kw.get("agent") == "audience_analyst":
            raise AgentRunError("simulated", raw_text="x", validation_error="x")
        return await real_run(**kw)

    monkeypatch.setattr(runner_with_chunks, "run", maybe_fail)

    graph = build_analysis_graph(runner_with_chunks)
    final = await graph.ainvoke(
        {
            "tenant_id": runner_with_chunks.retrieval.repo.tenant_id,
            "business_id": uuid4(),
            "industry": "fintech",
            "business_url": "https://example.test",
        }
    )
    assert final["audience"] is None
    assert final["brand"] is not None
    # Strategist still ran (the strategist's _summarize_prior handles None slots).
    assert final["final_strategy"] is not None
    # The error is captured.
    assert any("audience_analyst" in e for e in final.get("errors", []))


@pytest.mark.asyncio
async def test_graph_few_shot_injection(
    runner_with_chunks: AgentRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bizpulse.models.strategy import MarketingStrategy

    # 1. Create a dummy few shot MarketingStrategy
    dummy_strategy = MarketingStrategy.model_validate(
        {
            "tenant_id": str(runner_with_chunks.retrieval.repo.tenant_id),
            "business_id": str(uuid4()),
            "industry": "fintech",
            "brand": {
                "positioning": "past-positioning",
                "tone": "past-tone",
                "value_props": ["past-prop"],
                "citations": [{"chunk_id": _CHUNK_ID, "quote": "past-quote", "confidence": 0.99}],
            },
            "audience": {
                "primary": {
                    "name": "Past ICP",
                    "description": "past desc",
                    "motivations": [],
                    "pain_points": [],
                    "citations": [
                        {"chunk_id": _CHUNK_ID, "quote": "past-quote", "confidence": 0.99}
                    ],
                },
                "citations": [{"chunk_id": _CHUNK_ID, "quote": "past-quote", "confidence": 0.99}],
            },
            "recommendations": [
                {
                    "channel": "linkedin",
                    "action": "past action",
                    "rationale": "past rationale",
                    "evidence_chunk_ids": [_CHUNK_ID],
                    "confidence": 0.99,
                }
            ],
            "overall_confidence": 0.99,
            "summary": "past summary",
        }
    )

    # 2. Intercept the AgentRunner.run method to inspect kw["few_shot_examples"]
    captured_few_shots = {}
    real_run = runner_with_chunks.run

    async def mock_run(**kw):
        agent = kw.get("agent")
        few_shots = kw.get("few_shot_examples")
        captured_few_shots[agent] = few_shots
        return await real_run(**kw)

    monkeypatch.setattr(runner_with_chunks, "run", mock_run)

    # 3. Invoke graph with few_shots in the initial state
    graph = build_analysis_graph(runner_with_chunks)
    initial = {
        "tenant_id": runner_with_chunks.retrieval.repo.tenant_id,
        "business_id": uuid4(),
        "industry": "fintech",
        "business_url": "https://example.test",
        "few_shots": [dummy_strategy],
    }
    await graph.ainvoke(initial)

    # 4. Assertions on captured_few_shots
    # Brand analyst should have received the brand sub-component
    assert captured_few_shots["brand_analyst"] is not None
    assert len(captured_few_shots["brand_analyst"]) == 1
    assert captured_few_shots["brand_analyst"][0]["positioning"] == "past-positioning"

    # Audience analyst should have received the audience sub-component
    assert captured_few_shots["audience_analyst"] is not None
    assert len(captured_few_shots["audience_analyst"]) == 1
    assert captured_few_shots["audience_analyst"][0]["primary"]["name"] == "Past ICP"

    # Strategist should have received the full MarketingStrategy dump
    assert captured_few_shots["strategist"] is not None
    assert len(captured_few_shots["strategist"]) == 1
    assert captured_few_shots["strategist"][0]["summary"] == "past summary"
    assert captured_few_shots["strategist"][0]["brand"]["positioning"] == "past-positioning"
