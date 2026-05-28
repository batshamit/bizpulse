"""Unit and integration tests for the Daily Research Agent LangGraph pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from qdrant_client import QdrantClient

from bizpulse.agents.council import Council
from bizpulse.agents.research_graph import build_research_graph
from bizpulse.agents.runner import AgentRunner
from bizpulse.llm import CallableLLMClient
from bizpulse.models import (
    Chunk,
    ChunkMetadata,
    DailyResearchReport,
    EmbeddedChunk,
)
from bizpulse.models.common import SUPPORTED_INDUSTRIES
from bizpulse.retrieval import TenantQdrant
from bizpulse.retrieval.search import RetrievalEngine


class _Embedder:
    embed_dim = 4
    model = "fake"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.5, 0.5, 0.5, 0.5]] * len(texts)


_CHUNK_ID = str(uuid4())

_PROJECT_JSON = json.dumps(
    {
        "new_launches": ["DLF Sector 63", "Godrej Woods Phase 2"],
        "price_movements": ["Sector 63: Rs 15000/sqft to Rs 17000/sqft"],
        "uncertain_claims": ["12% guaranteed returns on commercial plots"],
        "citations": [
            {"chunk_id": _CHUNK_ID, "quote": "new launch in Sector 63", "confidence": 0.9}
        ],
    }
)

_POLICY_JSON = json.dumps(
    {
        "policy_updates": ["RBI holds repo rate at 6.5%"],
        "market_updates": ["Home loan inquiries up 10%"],
        "uncertain_claims": ["RERA registration number not yet issued for Godrej Woods Phase 2"],
        "citations": [
            {"chunk_id": _CHUNK_ID, "quote": "repo rate holds at 6.5%", "confidence": 0.95}
        ],
    }
)


@pytest.fixture
def runner_with_chunks(tmp_path: Path) -> AgentRunner:
    client = QdrantClient(path=str(tmp_path / "qd"))
    repo = TenantQdrant(uuid4(), client=client)
    repo.ensure_collection(vector_size=4)

    meta = ChunkMetadata(
        tenant_id=repo.tenant_id,
        business_id=uuid4(),
        industry="real_estate",
        source_url="https://realestate-test.example",
        source_type="about_page",
        content_hash="abcdef0123456789",
    )
    repo.upsert(
        [
            EmbeddedChunk(
                chunk=Chunk(
                    text="We build luxury apartments under the DLF brand in Gurugram.",
                    metadata=meta,
                ),
                vector=[1.0, 0.0, 0.0, 0.0],
                embed_model="x",
                embed_dim=4,
            )
        ]
    )
    retrieval = RetrievalEngine(repo, embedder=_Embedder())
    return retrieval


@pytest.mark.asyncio
async def test_research_graph_sequential_execution(
    runner_with_chunks: RetrievalEngine,
) -> None:
    # 1. Setup mock route for sequential testing
    captured_prompts = []

    def _route(_system: str, user: str) -> str:
        captured_prompts.append({"system": _system, "user": user})
        if "(DailyResearchReport)" in user:
            # We dynamically inject industry name to test it handles arbitrary industry string
            return json.dumps(
                {
                    "tenant_id": str(runner_with_chunks.repo.tenant_id),
                    "business_id": str(uuid4()),
                    "industry": "real_estate",
                    "most_important_update": "RBI holds repo rate at 6.5% keeping home loan costs steady.",
                    "market_and_entities": [
                        "DLF Sector 63 launched in Gurugram.",
                        "Godrej Woods Phase 2 announced in Noida.",
                    ],
                    "policy_and_news": ["RBI holds repo rate at 6.5%."],
                    "uncertainty_log": [
                        "12% guaranteed returns on commercial plots",
                        "RERA registration number not yet issued for Godrej Woods Phase 2",
                    ],
                    "overall_confidence": 0.9,
                    "citations": [
                        {
                            "chunk_id": _CHUNK_ID,
                            "quote": "repo rate holds at 6.5%",
                            "confidence": 0.95,
                        }
                    ],
                }
            )
        if "(ProjectTrackerOutput)" in user:
            return _PROJECT_JSON
        if "(PolicyTrackerOutput)" in user:
            return _POLICY_JSON
        return "{}"

    judge = CallableLLMClient(name="judge", vendor="fake", fn=_route)
    member = CallableLLMClient(name="m", vendor="fake", fn=_route)
    council = Council(members=[member], judge=judge, rounds=1)
    runner = AgentRunner(retrieval=runner_with_chunks, council=council, industry="real_estate")

    graph = build_research_graph(runner, sequential=True)
    initial = {
        "tenant_id": runner_with_chunks.repo.tenant_id,
        "business_id": uuid4(),
        "industry": "real_estate",
        "business_url": "https://realestate-test.example",
        "country": "IN",
        "state": "Haryana",
        "run_type": "daily_research",
    }

    final = await graph.ainvoke(initial)

    # Validate output schema
    report: DailyResearchReport = final.get("research_report")
    assert report is not None
    assert report.industry == "real_estate"
    assert (
        report.most_important_update
        == "RBI holds repo rate at 6.5% keeping home loan costs steady."
    )
    assert "DLF Sector 63 launched in Gurugram." in report.market_and_entities
    assert len(report.uncertainty_log) == 2
    assert "12% guaranteed returns on commercial plots" in report.uncertainty_log
    assert report.overall_confidence == 0.9

    # Assert that prompts were generated dynamically using real_estate ontology
    # project_tracker is run first
    project_prompt = next(p for p in captured_prompts if "(ProjectTrackerOutput)" in p["user"])
    # should contain entities/metrics from real_estate.yaml
    assert "project" in project_prompt["user"]
    assert "asset_class" in project_prompt["user"]
    assert "price-per-sqft trend" in project_prompt["user"]

    # policy_tracker is run second
    policy_prompt = next(p for p in captured_prompts if "(PolicyTrackerOutput)" in p["user"])
    # should contain regulations from real_estate.yaml
    assert "RERA" in policy_prompt["user"]
    assert "GST on under-construction property" in policy_prompt["user"]


@pytest.mark.asyncio
async def test_research_graph_parallel_execution(
    runner_with_chunks: RetrievalEngine,
) -> None:
    # 1. Setup mock route for parallel testing
    def _route(_system: str, user: str) -> str:
        if "(DailyResearchReport)" in user:
            return json.dumps(
                {
                    "tenant_id": str(runner_with_chunks.repo.tenant_id),
                    "business_id": str(uuid4()),
                    "industry": "real_estate",
                    "most_important_update": "Parallel update.",
                    "market_and_entities": [],
                    "policy_and_news": [],
                    "uncertainty_log": [],
                    "overall_confidence": 1.0,
                    "citations": [],
                }
            )
        if "(ProjectTrackerOutput)" in user:
            return _PROJECT_JSON
        if "(PolicyTrackerOutput)" in user:
            return _POLICY_JSON
        return "{}"

    judge = CallableLLMClient(name="judge", vendor="fake", fn=_route)
    member = CallableLLMClient(name="m", vendor="fake", fn=_route)
    council = Council(members=[member], judge=judge, rounds=1)
    runner = AgentRunner(retrieval=runner_with_chunks, council=council, industry="real_estate")

    graph = build_research_graph(runner, sequential=False)
    initial = {
        "tenant_id": runner_with_chunks.repo.tenant_id,
        "business_id": uuid4(),
        "industry": "real_estate",
        "business_url": "https://realestate-test.example",
        "run_type": "daily_research",
    }

    final = await graph.ainvoke(initial)
    report: DailyResearchReport = final.get("research_report")
    assert report is not None
    assert report.most_important_update == "Parallel update."


@pytest.mark.asyncio
async def test_dynamic_creation_for_new_domain(
    runner_with_chunks: RetrievalEngine,
) -> None:
    """Verify that adding a new YAML file to `industries/` automatically registers it,
    makes it valid, and enables the research graph to load it dynamically."""

    # 1. Create a temporary domain config in the industries folder
    industries_dir = Path(__file__).resolve().parents[1] / "industries"
    temp_yaml_path = industries_dir / "temp_crypto_trading.yaml"

    temp_domain_data = {
        "slug": "temp_crypto_trading",
        "name": "Crypto Trading",
        "description": "Digital assets, decentralized finance, and crypto exchanges.",
        "ontology": {
            "entities": ["crypto_token", "exchange_platform", "liquidity_pool"],
            "regulations": ["MiCA guidelines", "SEC spot ETF decisions", "FATF Travel Rule"],
            "metrics": ["24h volume", "total value locked", "gas fees"],
        },
        "competitor_seeds": ["binance.com", "coinbase.com"],
        "channel_weights": {"twitter": 1.0, "telegram": 0.9, "youtube": 0.5},
        "content_pillars": ["market_analysis", "regulatory_compliance"],
        "prompt_addendum": "Focus on high-volatility digital assets.",
    }

    # Write temp yaml
    try:
        with open(temp_yaml_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(temp_domain_data, f)

        # Clear any cached properties or force re-eval of SUPPORTED_INDUSTRIES
        # (It reads from directory dynamically so the new domain is active immediately!)
        assert "temp_crypto_trading" in SUPPORTED_INDUSTRIES

        # 2. Compile the research graph and check dynamic prompt content for the new domain
        captured_prompts = []

        def _route(_system: str, user: str) -> str:
            captured_prompts.append({"system": _system, "user": user})
            if "(DailyResearchReport)" in user:
                return json.dumps(
                    {
                        "tenant_id": str(runner_with_chunks.repo.tenant_id),
                        "business_id": str(uuid4()),
                        "industry": "temp_crypto_trading",
                        "most_important_update": "SEC approves spot Ethereum ETF.",
                        "market_and_entities": [],
                        "policy_and_news": [],
                        "uncertainty_log": [],
                        "overall_confidence": 0.95,
                        "citations": [],
                    }
                )
            if "(ProjectTrackerOutput)" in user:
                return _PROJECT_JSON
            if "(PolicyTrackerOutput)" in user:
                return _POLICY_JSON
            return "{}"

        judge = CallableLLMClient(name="judge", vendor="fake", fn=_route)
        member = CallableLLMClient(name="m", vendor="fake", fn=_route)
        council = Council(members=[member], judge=judge, rounds=1)
        runner = AgentRunner(
            retrieval=runner_with_chunks, council=council, industry="temp_crypto_trading"
        )

        graph = build_research_graph(runner, sequential=True)
        initial = {
            "tenant_id": runner_with_chunks.repo.tenant_id,
            "business_id": uuid4(),
            "industry": "temp_crypto_trading",
            "business_url": "https://crypto.example",
            "run_type": "daily_research",
        }

        final = await graph.ainvoke(initial)
        report: DailyResearchReport = final.get("research_report")
        assert report is not None
        assert report.industry == "temp_crypto_trading"
        assert report.most_important_update == "SEC approves spot Ethereum ETF."

        # Verify that project_tracker received the crypto-specific entities and metrics
        project_prompt = next(p for p in captured_prompts if "(ProjectTrackerOutput)" in p["user"])
        assert "crypto_token" in project_prompt["user"]
        assert "exchange_platform" in project_prompt["user"]
        assert "total value locked" in project_prompt["user"]

        # Verify that policy_tracker received crypto-specific regulations
        policy_prompt = next(p for p in captured_prompts if "(PolicyTrackerOutput)" in p["user"])
        assert "MiCA guidelines" in policy_prompt["user"]
        assert "SEC spot ETF decisions" in policy_prompt["user"]
        assert "FATF Travel Rule" in policy_prompt["user"]

    finally:
        # 3. Clean up the temp YAML file so the workspace remains pristine
        if temp_yaml_path.exists():
            temp_yaml_path.unlink()
