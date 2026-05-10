"""Background-task driver for POST /v1/businesses/{id}/analyze.

The HTTP handler creates a RunRecord(status='pending') and schedules
`run_analysis_background(run_id, business, country, state)` via FastAPI's
BackgroundTasks. The task:

    1. crawl the business URL with Playwright (30s budget); fall back to
       a synthetic industry-shaped seed if the crawl produces nothing
    2. embed chunks with GeminiEmbedder (768-dim, free tier) if a Google
       key is set; otherwise use a hash embedder (random retrieval but
       lets us prove wiring works)
    3. ingest into a per-tenant Qdrant (embedded path) collection
    4. invoke the LangGraph: 4 analysts -> strategist -> compliance_checker
    5. attach the compliance_report inside MarketingStrategy.compliance_report
    6. update the run with status='complete' + final_output

Failures are caught and the run is marked 'failed' with the error captured.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

from qdrant_client import QdrantClient

from bizpulse.agents import AgentRunner, Council
from bizpulse.agents.graph import build_analysis_graph
from bizpulse.ingest import IngestionPipeline
from bizpulse.ingest.crawler import PlaywrightCrawler
from bizpulse.llm.factory import build_clients
from bizpulse.llm.openai_compat import GroqClient, MistralClient, OpenRouterClient
from bizpulse.logging import get_logger
from bizpulse.models import Business, RawArtifact
from bizpulse.retrieval import GeminiEmbedder, RetrievalEngine, TenantQdrant
from bizpulse.storage import Store, get_default_store

log = get_logger(__name__)


_QDRANT_BASE = Path(
    os.environ.get("BIZPULSE_QDRANT_DIR", str(Path(tempfile.gettempdir()) / "bizpulse-qdrant"))
)


class _HashEmbedder:
    """Fallback when no embedding key is available or Gemini is unreachable."""

    embed_dim = 768
    model = "hash-fallback"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            h = hashlib.sha512(t.encode()).digest()
            # Fan out 64 bytes to 768 floats (768 = 64 * 12).
            vec: list[float] = []
            for byte in h[:64]:
                v = byte / 255.0
                vec.extend([v, v ** 0.5, 1 - v, v * 2 - 1] * 3)
            out.append(vec[:768])
        return out


class _SafeEmbedder:
    """Wraps a primary embedder; on any runtime failure, falls back to a
    secondary embedder for the rest of the run. Lets the demo keep moving
    when Google's embeddings API has a bad day or returns 404 on a model
    name that quietly changed."""

    def __init__(self, primary, fallback):
        self.primary = primary
        self.fallback = fallback
        self.embed_dim = getattr(primary, "embed_dim", getattr(fallback, "embed_dim", 768))
        self.model = getattr(primary, "model", "")
        self._fallen_back = False

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if self._fallen_back:
            return await self.fallback.embed(texts)
        try:
            return await self.primary.embed(texts)
        except Exception as exc:  # noqa: BLE001 — vendor SDKs raise heterogeneously
            log.warning(
                "runner.embedder.primary_failed_falling_back",
                primary=self.model,
                error=str(exc)[:200],
            )
            self._fallen_back = True
            self.embed_dim = getattr(self.fallback, "embed_dim", 768)
            self.model = getattr(self.fallback, "model", "fallback")
            return await self.fallback.embed(texts)


def _pick_embedder():
    """Wraps a Gemini embedder with a hash-embedder fallback so a Gemini
    outage / model rename doesn't take the whole run down."""
    fallback = _HashEmbedder()
    if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
        try:
            return _SafeEmbedder(primary=GeminiEmbedder(), fallback=fallback)
        except Exception as exc:  # noqa: BLE001
            log.warning("runner.embedder.gemini_init_failed", error=str(exc)[:200])
    return fallback


def _pick_council() -> Council | None:
    """Build the cheapest live council. Caller handles None."""
    members = build_clients(prefer=["groq", "google", "mistral", "anthropic", "openrouter", "openai"])
    if not members:
        return None
    # Prefer Claude Haiku via OpenRouter for the judge if available
    # (best at structured synthesis), else Mistral, else first member.
    judge = members[0]
    fallback = None
    by_vendor = {m.vendor: m for m in members}
    if "openrouter" in by_vendor:
        try:
            judge = OpenRouterClient(model="anthropic/claude-haiku-4-5")
        except Exception:
            pass
    elif "mistral" in by_vendor:
        try:
            judge = MistralClient(model="mistral-small-latest")
        except Exception:
            pass
    elif "groq" in by_vendor:
        try:
            judge = GroqClient(model="llama-3.3-70b-versatile")
        except Exception:
            pass
    fallback = next((m for m in members if m is not judge), None)
    return Council(
        members=members,
        judge=judge,
        fallback_judge=fallback,
        rounds=1,
        max_tokens=1536,
    )


async def _try_crawl(url: str, tenant_id: UUID, business_id: UUID) -> list[RawArtifact]:
    """Best-effort Playwright crawl with a 30s wall budget. Returns empty
    list on failure — caller should fall back to a synthetic seed."""
    crawler = PlaywrightCrawler(nav_timeout_ms=15_000, request_timeout_ms=15_000)
    artifacts: list[RawArtifact] = []
    try:
        agen: AsyncIterator[RawArtifact] = crawler.crawl(
            url, tenant_id=tenant_id, business_id=business_id, max_pages=6
        )

        async def _collect():
            async for a in agen:
                artifacts.append(a)
                # Bail out early once we have enough — first 4 pages are
                # usually the most informative (home + about + pricing + blog).
                if len(artifacts) >= 4:
                    break

        await asyncio.wait_for(_collect(), timeout=45.0)
    except asyncio.TimeoutError:
        log.warning("runner.crawl.timeout", url=url, partial=len(artifacts))
    except Exception as exc:  # noqa: BLE001 — Playwright raises many types
        log.warning("runner.crawl.failed", url=url, error=str(exc)[:200])
    return artifacts


def _synthetic_artifact(business: Business) -> RawArtifact:
    """Industry-shaped placeholder when crawl fails. Keeps the demo moving."""
    industry = business.industry or "fintech"
    text = (
        f"Hero. {business.url} is a {industry} business. "
        "Pricing details, team information, and product offerings would normally appear here. "
        "Live crawl was unavailable for this run — strategy generated against a minimal seed.\n\n"
        "About. This business operates in the "
        f"{industry} vertical and serves customers across multiple geographies. "
        "Brand positioning and detailed value propositions are inferred by the agent council "
        "from the URL and industry context.\n\n"
        "Contact. Reach out via the business website for products, pricing, and partnerships."
    )
    return RawArtifact(
        tenant_id=business.tenant_id,
        business_id=business.id,
        source_url=business.url,
        source_type="website_page",
        content_hash=RawArtifact.hash_text(text),
        extracted_text=text,
    )


async def run_analysis_background(
    *,
    run_id: UUID,
    business: Business,
    country: str = "IN",
    state: str | None = None,
) -> None:
    """Run the analysis pipeline in the background. Updates the run record
    in `get_default_store()` as it progresses."""
    store: Store = get_default_store()

    def _set(status: str, *, error: str | None = None) -> None:
        try:
            store.update_run_status(run_id, status, error=error)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001
            log.warning("runner.set_status.failed", run_id=str(run_id), error=str(exc))

    log.info("runner.analyze.start", run_id=str(run_id), url=business.url)
    council = _pick_council()
    if council is None:
        _set("failed", error="No LLM API keys available — set at least one vendor key in .env.")
        return

    # 1. Crawl.
    _set("ingesting")
    artifacts = await _try_crawl(business.url, business.tenant_id, business.id)
    if not artifacts:
        artifacts = [_synthetic_artifact(business)]

    # 2. Ingest (chunk + embed + upsert).
    _set("embedding")
    embedder = _pick_embedder()
    qd_dir = _QDRANT_BASE / f"run-{run_id}"
    qd_dir.mkdir(parents=True, exist_ok=True)
    repo = TenantQdrant(business.tenant_id, client=QdrantClient(path=str(qd_dir)))
    pipe = IngestionPipeline(repo, embedder, industry=business.industry, batch_size=24)
    try:
        await pipe.ingest(artifacts)
    except Exception as exc:  # noqa: BLE001
        log.warning("runner.ingest.failed", error=str(exc)[:300])
        _set("failed", error=f"ingest failed: {exc}")
        return

    # 3. Run the LangGraph.
    _set("analyzing")
    runner = AgentRunner(
        retrieval=RetrievalEngine(repo, embedder=embedder),  # type: ignore[arg-type]
        council=council,
        industry=business.industry,
    )
    graph = build_analysis_graph(runner)

    try:
        final = await graph.ainvoke({
            "tenant_id": business.tenant_id,
            "business_id": business.id,
            "industry": business.industry or "fintech",
            "business_url": business.url,
            "country": country,
            "state": state,
        })
    except Exception as exc:  # noqa: BLE001
        log.warning("runner.graph.failed", error=str(exc)[:300])
        _set("failed", error=f"graph invocation failed: {exc}")
        return

    strategy = final.get("final_strategy")
    compliance = final.get("compliance_report")
    if strategy is None:
        errors = final.get("errors", [])
        _set("failed", error="; ".join(errors)[:500] or "no final_strategy produced")
        return

    # 4. Attach compliance to the strategy + persist via run update.
    if compliance is not None:
        try:
            strategy = strategy.model_copy(update={"compliance_report": compliance})
        except Exception:
            pass

    _persist_final_output(store=store, run_id=run_id, strategy=strategy)
    _set("complete")
    log.info("runner.analyze.complete", run_id=str(run_id))


def _persist_final_output(*, store: Store, run_id: UUID, strategy) -> None:
    """Stuff the final MarketingStrategy onto the run.

    InMemoryStore: just attach via model_copy on the existing record.
    PostgresStore: writes JSONB into runs.output (added by the schema).
    """
    try:
        run = store.get_run(run_id)
    except Exception:
        run = None
    if run is None:
        return

    # In-memory: replace the dict entry directly.
    try:
        from bizpulse.storage.memory import InMemoryStore
        if isinstance(store, InMemoryStore):
            updated = run.model_copy(update={"final_output": strategy})
            # Internal: just rewrite the dict slot.
            store._runs[run_id] = updated  # type: ignore[attr-defined]
            return
    except Exception:
        pass

    # Postgres: write into runs.output JSONB.
    try:
        from bizpulse.storage.postgres import PostgresStore
        if isinstance(store, PostgresStore):
            with store._pool.connection() as conn, conn.cursor() as cur:  # type: ignore[attr-defined]
                cur.execute(
                    "UPDATE runs SET output = %s::jsonb WHERE id = %s",
                    (strategy.model_dump_json(), str(run_id)),
                )
            return
    except Exception as exc:  # noqa: BLE001
        log.warning("runner.persist.failed", error=str(exc)[:200])
