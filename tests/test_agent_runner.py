"""Tests for AgentRunner: end-to-end with mocked retrieval + mocked Council."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import BaseModel
from qdrant_client import QdrantClient

from bizpulse.agents import (
    AgentRunError,
    AgentRunner,
    Council,
    extract_json,
)
from bizpulse.llm import FakeLLMClient, ScriptedLLMClient
from bizpulse.models import (
    Chunk,
    ChunkMetadata,
    EmbeddedChunk,
)
from bizpulse.retrieval import TenantQdrant
from bizpulse.retrieval.search import RetrievalEngine


class _ToyOutput(BaseModel):
    summary: str
    confidence: float


class _FakeEmbedder:
    embed_dim = 4
    model = "fake"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.5, 0.5, 0.5, 0.5]] * len(texts)


@pytest.fixture
def runner_with_chunks(tmp_path: Path) -> AgentRunner:
    """Pre-populate Qdrant with a few chunks; build a runner backed by a
    one-member Council (echoes whatever the judge says)."""
    client = QdrantClient(path=str(tmp_path / "qdrant"))
    repo = TenantQdrant(uuid4(), client=client)
    repo.ensure_collection(vector_size=4)

    meta = ChunkMetadata(
        tenant_id=repo.tenant_id,
        business_id=uuid4(),
        industry="fintech",
        source_url="https://example.com/x",
        source_type="about_page",
        content_hash="abcdef0123456789",
    )
    repo.upsert(
        [
            EmbeddedChunk(
                chunk=Chunk(text="We build a neobank for gig workers.", metadata=meta),
                vector=[1.0, 0.0, 0.0, 0.0],
                embed_model="fake",
                embed_dim=4,
            ),
            EmbeddedChunk(
                chunk=Chunk(
                    text="Pricing: ₹0 monthly, in-app foreign-exchange margin.", metadata=meta
                ),
                vector=[0.0, 1.0, 0.0, 0.0],
                embed_model="fake",
                embed_dim=4,
            ),
        ]
    )
    retrieval = RetrievalEngine(repo, embedder=_FakeEmbedder())
    judge = FakeLLMClient(
        name="judge",
        vendor="fake",
        response='{"summary": "fintech neobank for gig workers", "confidence": 0.85}',
    )
    member = FakeLLMClient(
        name="member",
        vendor="fake",
        response='{"summary": "neobank", "confidence": 0.7}',
    )
    council = Council(members=[member], judge=judge, rounds=1)
    return AgentRunner(retrieval=retrieval, council=council, industry="fintech")


@pytest.mark.asyncio
async def test_run_returns_typed_output(runner_with_chunks: AgentRunner) -> None:
    result = await runner_with_chunks.run(
        agent="brand_analyst",
        task="Summarize the brand positioning",
        output_schema=_ToyOutput,
        query_text="positioning",
    )
    assert isinstance(result.output, _ToyOutput)
    assert result.output.summary == "fintech neobank for gig workers"
    assert result.output.confidence == 0.85
    assert result.repair_attempted is False
    assert result.context_chunks  # retrieval was actually performed


@pytest.mark.asyncio
async def test_repair_path_recovers_from_bad_json(tmp_path: Path) -> None:
    """First judge response is broken JSON; repair re-asks and gets valid JSON."""
    client = QdrantClient(path=str(tmp_path / "qdrant"))
    repo = TenantQdrant(uuid4(), client=client)
    repo.ensure_collection(vector_size=4)
    retrieval = RetrievalEngine(repo, embedder=_FakeEmbedder())

    judge = ScriptedLLMClient(
        name="judge",
        vendor="fake",
        responses=[
            "broken{not-json",  # initial debate
            '{"summary": "repaired", "confidence": 0.5}',  # repair call
        ],
    )
    member = FakeLLMClient(name="m", vendor="fake", response='{"summary": "x", "confidence": 0.1}')
    council = Council(members=[member], judge=judge, rounds=1)
    runner = AgentRunner(retrieval=retrieval, council=council)

    result = await runner.run(
        agent="brand_analyst",
        task="task",
        output_schema=_ToyOutput,
        query_text="q",
    )
    assert result.repair_attempted is True
    assert result.output.summary == "repaired"


@pytest.mark.asyncio
async def test_repair_failure_raises_agent_run_error(tmp_path: Path) -> None:
    client = QdrantClient(path=str(tmp_path / "qdrant"))
    repo = TenantQdrant(uuid4(), client=client)
    repo.ensure_collection(vector_size=4)
    retrieval = RetrievalEngine(repo, embedder=_FakeEmbedder())
    judge = ScriptedLLMClient(name="judge", vendor="fake", responses=["bad", "still bad"])
    member = FakeLLMClient(name="m", vendor="fake", response="x")
    council = Council(members=[member], judge=judge, rounds=1)
    runner = AgentRunner(retrieval=retrieval, council=council)

    with pytest.raises(AgentRunError, match="failed to produce"):
        await runner.run(
            agent="brand_analyst",
            task="task",
            output_schema=_ToyOutput,
            query_text="q",
        )


# ---- extract_json ----------------------------------------------------------


def test_extract_json_direct() -> None:
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced() -> None:
    text = 'Sure, here you go:\n```json\n{"a": 1}\n```\nLet me know if you need more.'
    assert extract_json(text) == {"a": 1}


def test_extract_json_inline() -> None:
    text = 'Quick reply: {"a": 1, "b": [1,2]} and that\'s it.'
    assert extract_json(text) == {"a": 1, "b": [1, 2]}


def test_extract_json_array() -> None:
    text = "[1, 2, 3]"
    assert extract_json(text) == [1, 2, 3]


def test_extract_json_no_match_raises() -> None:
    with pytest.raises(ValueError, match="no parseable JSON"):
        extract_json("nothing parseable here")
