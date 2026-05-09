"""End-to-end EvalRunner test against fakes — uses the shipped neobank golden."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from qdrant_client import QdrantClient

from bizpulse.agents.council import Council
from bizpulse.eval import EvalRunner, GoldenExample, load_golden
from bizpulse.llm import FakeLLMClient


GOLDEN = Path(__file__).resolve().parents[1] / "tests" / "eval" / "golden" / "fintech" / "neobank_v1.json"
# In test runs, __file__'s parents[1] is repo/tests, so re-anchor:
REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_NEOBANK = REPO_ROOT / "eval" / "golden" / "fintech" / "neobank_v1.json"


class _FakeEmbedder:
    embed_dim = 4
    model = "fake"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            h = hashlib.sha256(t.encode()).digest()
            out.append([h[0] / 255, h[1] / 255, h[2] / 255, h[3] / 255])
        return out


def test_load_neobank_golden_validates() -> None:
    g = load_golden(GOLDEN_NEOBANK)
    assert isinstance(g, GoldenExample)
    assert g.industry == "fintech"
    assert len(g.chunks) >= 2
    assert len(g.tasks) >= 1


@pytest.mark.asyncio
async def test_eval_runner_executes_neobank_golden(tmp_path: Path) -> None:
    """Synth: judge returns a hard-coded BrandAnalysis JSON; we verify the
    runner ingests, runs, scores, and reports."""
    golden = load_golden(GOLDEN_NEOBANK)
    chunk_ids: list[str] = []  # we'll fill these from a peek into Qdrant

    canned_brand = {
        "positioning": "compliance-first neobank for gig-economy workers",
        "tone": "trustworthy and regulation-aware",
        "value_props": [
            "full-KYC accounts approved within 24 hours",
            "instant credit-line for platform workers",
            "RBI digital-lending guideline compliance baked in",
        ],
        "citations": [
            {"chunk_id": "00000000-0000-0000-0000-000000000001", "quote": "neobank for gig", "confidence": 0.9}
        ],
    }
    judge = FakeLLMClient(name="judge", vendor="fake", response=json.dumps(canned_brand))
    member = FakeLLMClient(name="m", vendor="fake", response=json.dumps(canned_brand))

    def council_factory() -> Council:
        return Council(members=[member], judge=judge, rounds=1)

    runner = EvalRunner(
        embedder=_FakeEmbedder(),
        qdrant_client_factory=lambda: QdrantClient(path=str(tmp_path / f"qd-{golden.id}")),
        council_factory=council_factory,
    )

    report = await runner.run(golden)

    assert report.golden_id == golden.id
    assert report.industry == "fintech"
    assert report.n_tasks == 1
    # canned response cites chunk 00..01 — that's not a REAL retrieved chunk so
    # citation_count > 0 but citations_meet_min may pass (we only need >= 1
    # cited id present in the dump). Test the structural pieces:
    s0 = report.task_scores[0]
    assert s0.task_id == "brand-positioning"
    assert s0.schema_valid is True
    # keyword check: "gig" + "compliance" both present in canned response
    assert all(s0.keyword_hits.values())
    # forbidden: "crypto"/"BTC" not in canned response
    assert not any(s0.forbidden_hits.values())
