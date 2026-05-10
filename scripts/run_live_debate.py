#!/usr/bin/env python
"""Live end-to-end demo: ingest the shipped neobank golden, run brand_analyst
through a real LLM Council, print the citation-grounded Pydantic output.

Picks up whichever vendor keys are in `.env` (any one is enough).
By default uses Gemini 2.5 Flash (free tier works) — pass `--vendor` to switch.

Usage:
    .venv/bin/python scripts/run_live_debate.py
    .venv/bin/python scripts/run_live_debate.py --agent brand_analyst --golden fintech/neobank_v1.json
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

# Ensure imports resolve when run from repo root.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qdrant_client import QdrantClient

from bizpulse.agents import AgentRunner, Council
from bizpulse.eval.golden import load_golden
from bizpulse.ingest import IngestionPipeline
from bizpulse.llm.factory import build_clients
from bizpulse.models import (
    AudienceAnalysis,
    BrandAnalysis,
    CompetitiveLandscape,
    ContentAudit,
    RawArtifact,
)
from bizpulse.retrieval import RetrievalEngine, TenantQdrant


SCHEMAS = {
    "brand_analyst": BrandAnalysis,
    "audience_analyst": AudienceAnalysis,
    "competitor_scout": CompetitiveLandscape,
    "content_auditor": ContentAudit,
}


class HashEmbedder:
    """4-d deterministic embedder so we don't need TEI running."""

    embed_dim = 4
    model = "hash-embed"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [
            [b / 255 for b in hashlib.sha256(t.encode()).digest()[:4]]
            for t in texts
        ]


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--golden", default="fintech/neobank_v1.json",
                   help="path under tests/eval/golden/")
    p.add_argument("--agent", default="brand_analyst",
                   choices=list(SCHEMAS),
                   help="which analyst to run")
    p.add_argument("--top-k", type=int, default=4)
    args = p.parse_args()

    members = build_clients()
    if not members:
        sys.exit(
            "No LLM keys found. Set at least one of ANTHROPIC_API_KEY, "
            "GOOGLE_API_KEY, OPENAI_API_KEY in .env."
        )
    print(f"[council] members: {[m.name for m in members]}")

    # Single-vendor council degrades to "ask once, judge yourself".
    council = Council(members=members, judge=members[0], rounds=1)

    # Tenant + Qdrant scoped to this run only (tempdir).
    tdir = Path(tempfile.mkdtemp(prefix="bzp-live-"))
    repo = TenantQdrant(uuid4(), client=QdrantClient(path=str(tdir / "qd")))

    # Ingest the golden's chunks.
    g = load_golden(args.golden)
    text = "\n\n".join(c.text for c in g.chunks)
    embedder = HashEmbedder()
    pipe = IngestionPipeline(repo, embedder, industry=g.industry)
    n_chunks = await pipe.ingest([
        RawArtifact(
            tenant_id=repo.tenant_id,
            business_id=uuid4(),
            source_url=g.business_url,
            source_type="website_page",
            content_hash=RawArtifact.hash_text(text),
            extracted_text=text,
        )
    ])
    print(f"[ingest]  {n_chunks} chunks indexed for golden {g.id!r}")

    # Run.
    runner = AgentRunner(retrieval=RetrievalEngine(repo, embedder=embedder),
                         council=council, industry=g.industry)
    schema = SCHEMAS[args.agent]

    task = next(
        (t.task for t in g.tasks if t.agent == args.agent),
        f"Produce a {schema.__name__} for this business.",
    )

    print(f"[run]     {args.agent} ({members[0].name})...")
    res = await runner.run(
        agent=args.agent,
        task=task,
        output_schema=schema,
        query_text=args.agent.replace("_", " "),
        top_k=args.top_k,
    )

    print()
    print(f"  cost:    ${res.council.cost_usd:.5f}")
    print(f"  time:    {res.latency_ms:.0f}ms")
    print(f"  repaired:{res.repair_attempted}")
    print()
    print(f"=== {schema.__name__} ===")
    print(res.output.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
