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
import re
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

from qdrant_client import QdrantClient

from bizpulse.agents import AgentRunner, Council
from bizpulse.agents.graph import build_analysis_graph
from bizpulse.config import settings
from bizpulse.ingest import IngestionPipeline
from bizpulse.ingest.crawler import PlaywrightCrawler
from bizpulse.llm import LLMClient
from bizpulse.llm.factory import ollama_chat_client
from bizpulse.llm.openai_compat import groq_client, mistral_client, openrouter_client
from bizpulse.logging import get_logger
from bizpulse.models import Business, RawArtifact
from bizpulse.retrieval import GeminiEmbedder, OllamaEmbeddings, RetrievalEngine, TenantQdrant
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
                vec.extend([v, v**0.5, 1 - v, v * 2 - 1] * 3)
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
        except Exception as exc:
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
    """Pick the best available embedder with a hash fallback.
    Order: Ollama (if configured) -> Gemini (if key set) -> Hash fallback."""
    fallback = _HashEmbedder()

    # Check for Ollama (using port 11434 as a hint or if explicitly configured)
    if "11434" in settings.embed_base_url or "ollama" in settings.embed_model.lower():
        try:
            return _SafeEmbedder(primary=OllamaEmbeddings(), fallback=fallback)
        except Exception as exc:
            log.warning("runner.embedder.ollama_init_failed", error=str(exc)[:200])

    if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
        try:
            return _SafeEmbedder(primary=GeminiEmbedder(), fallback=fallback)
        except Exception as exc:
            log.warning("runner.embedder.gemini_init_failed", error=str(exc)[:200])
    return fallback


def _check_ollama_model_sync(model_name: str, base_url: str) -> bool:
    """Synchronously check if a model exists in local Ollama tags."""
    try:
        import urllib.parse

        import httpx

        parsed = urllib.parse.urlparse(base_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        with httpx.Client(timeout=2.0) as client:
            r = client.get(f"{origin}/api/tags")
            if r.status_code == 200:
                data = r.json()
                models = [m["name"] for m in data.get("models", [])]
                return model_name in models or f"{model_name}:latest" in models
    except Exception:
        pass
    return False


def _pick_council(num_llms: int | None = None, speed: str = "general") -> Council | None:
    """Build a council preferring local Ollama if available, then fallback vendors, unless speed is ultra_fast."""
    members: list[LLMClient] = []

    # If speed is ultra_fast, prioritize high-speed Cloud APIs (Google Gemini and Groq)
    if speed == "ultra_fast":
        if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
            from bizpulse.llm.gemini_client import GeminiClient

            models_str = os.environ.get(
                "GEMINI_MODELS", os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
            )
            for m in [x.strip() for x in models_str.split(",") if x.strip()]:
                members.append(GeminiClient(model=m))

        if os.environ.get("GROQ_API_KEY"):
            models_str = os.environ.get(
                "GROQ_MODELS", os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
            )
            for m in [x.strip() for x in models_str.split(",") if x.strip()]:
                members.append(groq_client(model=m))

        # Add local models as fallbacks just in case cloud fails
        if (
            "11434" in settings.llm_base_url
            or "8800" in settings.llm_base_url
            or "vllm" in settings.llm_base_url.lower()
        ):
            if "11434" in settings.llm_base_url:
                primary_model = (
                    "gemma2:27b"
                    if _check_ollama_model_sync("gemma2:27b", settings.llm_base_url)
                    else "gemma2:9b"
                )
                qwen_model = (
                    "qwen2.5:14b"
                    if _check_ollama_model_sync("qwen2.5:14b", settings.llm_base_url)
                    else "granite3.2:8b"
                )
                members.append(ollama_chat_client(model=primary_model))
                members.append(ollama_chat_client(model=qwen_model))
            else:
                members.append(ollama_chat_client())

        if os.environ.get("MISTRAL_API_KEY"):
            models_str = os.environ.get(
                "MISTRAL_MODELS", os.environ.get("MISTRAL_MODEL", "mistral-small-latest")
            )
            for m in [x.strip() for x in models_str.split(",") if x.strip()]:
                members.append(mistral_client(model=m))

        if os.environ.get("OPENROUTER_API_KEY"):
            models_str = os.environ.get(
                "OPENROUTER_MODELS", os.environ.get("OPENROUTER_MODEL", "anthropic/claude-haiku-4-5")
            )
            for m in [x.strip() for x in models_str.split(",") if x.strip()]:
                members.append(openrouter_client(model=m))

    else:
        # Default local-first routing
        # Try local LLM (Ollama or local vLLM) first as it's local and cost-free
        if (
            "11434" in settings.llm_base_url
            or "8800" in settings.llm_base_url
            or "vllm" in settings.llm_base_url.lower()
        ):
            if "11434" in settings.llm_base_url:
                # Local Ollama Council (Optimized to fit in GPU VRAM with zero CPU fallback):
                # - gemma2:27b as primary judge (dynamic fallback to gemma2:9b)
                # - qwen2.5:14b as specified (dynamic fallback to granite3.2:8b)
                # - gemma2:9b as third member (dynamic fallback to granite3.2:8b)
                primary_model = (
                    "gemma2:27b"
                    if _check_ollama_model_sync("gemma2:27b", settings.llm_base_url)
                    else "gemma2:9b"
                )
                qwen_model = (
                    "qwen2.5:14b"
                    if _check_ollama_model_sync("qwen2.5:14b", settings.llm_base_url)
                    else "granite3.2:8b"
                )
                gemma_model = (
                    "gemma2:9b"
                    if _check_ollama_model_sync("gemma2:9b", settings.llm_base_url)
                    else "granite3.2:8b"
                )
                members.append(ollama_chat_client(model=primary_model))
                members.append(ollama_chat_client(model=qwen_model))
                members.append(ollama_chat_client(model=gemma_model))
            else:
                members.append(ollama_chat_client())

                # Check if GPU-accelerated GGUF servers are running on 8802/8803, and prioritize them over CPU Ollama
                qwen14b_gguf_gpu_active = False
                try:
                    import httpx
                    resp = httpx.get("http://127.0.0.1:8802/v1/models", timeout=0.5)
                    if resp.status_code == 200:
                        members.append(ollama_chat_client(model="qwen2.5:14b", base_url="http://127.0.0.1:8802/v1"))
                        qwen14b_gguf_gpu_active = True
                except Exception:
                    pass

                granite_gpu_active = False
                try:
                    import httpx
                    resp = httpx.get("http://127.0.0.1:8803/v1/models", timeout=0.5)
                    if resp.status_code == 200:
                        members.append(ollama_chat_client(model="granite3.2:8b", base_url="http://127.0.0.1:8803/v1"))
                        granite_gpu_active = True
                except Exception:
                    pass

                # If local Ollama is also running on port 11434, append its models to the council as local fallbacks
                ollama_url = "http://127.0.0.1:11434/v1"
                for local_model in ["gemma2:27b", "qwen2.5:14b", "gemma2:9b", "granite3.2:8b"]:
                    # Skip adding them as CPU fallbacks if we already have them running on GPU
                    if local_model == "qwen2.5:14b" and qwen14b_gguf_gpu_active:
                        continue
                    if local_model == "granite3.2:8b" and granite_gpu_active:
                        continue
                    if _check_ollama_model_sync(local_model, ollama_url):
                        members.append(ollama_chat_client(model=local_model, base_url=ollama_url))

        if os.environ.get("MISTRAL_API_KEY"):
            models_str = os.environ.get(
                "MISTRAL_MODELS", os.environ.get("MISTRAL_MODEL", "mistral-small-latest")
            )
            for m in [x.strip() for x in models_str.split(",") if x.strip()]:
                members.append(mistral_client(model=m))

        if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
            from bizpulse.llm.gemini_client import GeminiClient

            models_str = os.environ.get(
                "GEMINI_MODELS", os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
            )
            for m in [x.strip() for x in models_str.split(",") if x.strip()]:
                members.append(GeminiClient(model=m))

        if os.environ.get("GROQ_API_KEY"):
            models_str = os.environ.get(
                "GROQ_MODELS", os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
            )
            for m in [x.strip() for x in models_str.split(",") if x.strip()]:
                members.append(groq_client(model=m))

        if os.environ.get("OPENROUTER_API_KEY"):
            models_str = os.environ.get(
                "OPENROUTER_MODELS", os.environ.get("OPENROUTER_MODEL", "anthropic/claude-haiku-4-5")
            )
            for m in [x.strip() for x in models_str.split(",") if x.strip()]:
                members.append(openrouter_client(model=m))

    if not members:
        return None

    # Pick up to num_llms members
    if num_llms is not None and num_llms > 0:
        members = members[:num_llms]

    primary = members[0]

    # Pick fallback judge: prefer another local (ollama/vllm) member first, if available
    fallback: LLMClient | None = None
    for member in members:
        if member.name != primary.name and (
            "127.0.0.1" in getattr(member, "base_url", "")
            or "localhost" in getattr(member, "base_url", "")
        ):
            fallback = member
            break

    if fallback is None:
        for member in members:
            if member.vendor != primary.vendor:
                fallback = member
                break

    rounds = 2 if len(members) > 1 else 1

    return Council(
        members=members,
        judge=primary,
        fallback_judge=fallback,
        rounds=rounds,
        # 3072 gives MarketingStrategy (the biggest schema) room to fit + a
        # repair pass; smaller schemas use fewer tokens and don't pay extra.
        max_tokens=4096,
    )


# Pattern matches transient vendor / network failures the user typically
# wants us to retry through, not crash on. Anything matching this regex
# (case-insensitive) gets up to 2 retries with exponential backoff.
_TRANSIENT_RE = re.compile(
    r"(429|502|503|504|"
    r"rate.?limit|TPM|RPM|"
    r"timeout|"
    r"service.?(tier|capacity|unavailable)|"
    r"overloaded|"
    r"upstream)",
    re.IGNORECASE,
)
_RETRY_BACKOFFS_SEC = (8.0, 24.0)  # two retries → ~32s extra worst case


async def _invoke_graph_with_retry(graph, initial_state):
    """Run the LangGraph; retry on transient errors with exponential backoff.

    Non-transient errors propagate on the first occurrence — we don't want
    to retry a schema-validation bug 3 times. Match against _TRANSIENT_RE
    on the str(exception) — covers vendor 429/413/5xx + asyncio TimeoutError
    text + Groq/OpenRouter/Mistral specific phrasing without depending on
    each SDK's exception hierarchy.
    """
    last_exc: Exception | None = None
    for attempt in range(1 + len(_RETRY_BACKOFFS_SEC)):
        try:
            return await graph.ainvoke(initial_state)
        except Exception as exc:
            last_exc = exc
            msg = str(exc)
            transient = bool(_TRANSIENT_RE.search(msg))
            if not transient or attempt >= len(_RETRY_BACKOFFS_SEC):
                break
            wait_s = _RETRY_BACKOFFS_SEC[attempt]
            log.warning(
                "runner.graph.transient_retrying",
                attempt=attempt + 1,
                wait_s=wait_s,
                error=msg[:200],
            )
            await asyncio.sleep(wait_s)
    assert last_exc is not None
    raise last_exc


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
    except Exception as exc:
        log.warning("runner.crawl.failed", url=url, error=str(exc)[:200])
    return artifacts


async def _fetch_google_search_artifacts(
    business: Business,
    country: str,
    state: str | None,
) -> list[RawArtifact]:
    """Queries the Google Custom Search API for policy/trade, scarcity, deals,

    and innovations, wrapping results as RawArtifacts.
    """
    from bizpulse.retrieval.web_search import GoogleSearchClient

    client = GoogleSearchClient()
    if not client.api_key or not client.cse_id:
        return []

    log.info(
        "runner.google_search.start",
        business_id=str(business.id),
        industry=business.industry,
    )
    results = await client.gather_all_perspectives(
        business_url=business.url,
        industry=business.industry or "general",
        country=country,
        state=state,
    )

    artifacts = []
    for r in results:
        text = f"Title: {r['title']}\nSnippet: {r['snippet']}\nLink: {r['link']}"
        artifacts.append(
            RawArtifact(
                tenant_id=business.tenant_id,
                business_id=business.id,
                source_url=r["link"],
                source_type="website_page",
                content_hash=RawArtifact.hash_text(text),
                extracted_text=text,
            )
        )
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


def _user_context_artifact(business: Business, context: str) -> RawArtifact:
    """Wraps user-provided context (policies, extra reports) as a RawArtifact."""
    return RawArtifact(
        tenant_id=business.tenant_id,
        business_id=business.id,
        source_url=f"{business.url}/#user-context",
        source_type="user_context",
        content_hash=RawArtifact.hash_text(context),
        extracted_text=context,
    )


async def _heartbeat_sender(run_id: UUID, store: Store, stop_event: asyncio.Event) -> None:
    import socket
    import os
    hostname = socket.gethostname()
    pid = os.getpid()
    
    while not stop_event.is_set():
        try:
            if hasattr(store, "heartbeat_run"):
                store.heartbeat_run(run_id, hostname, pid)
        except Exception as exc:
            log.warning("runner.heartbeat.failed", run_id=str(run_id), error=str(exc))
        
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=15.0)
        except asyncio.TimeoutError:
            pass


async def run_analysis_background(
    *,
    run_id: UUID,
    business: Business,
    country: str = "IN",
    state: str | None = None,
    additional_context: str | None = None,
    num_llms: int | None = None,
    run_type: str = "marketing_strategy",
    speed: str = "general",
) -> None:
    store = get_default_store()
    stop_event = asyncio.Event()
    heartbeat_task = asyncio.create_task(_heartbeat_sender(run_id, store, stop_event))
    try:
        await _run_analysis_background_impl(
            run_id=run_id,
            business=business,
            country=country,
            state=state,
            additional_context=additional_context,
            num_llms=num_llms,
            run_type=run_type,
            speed=speed,
        )
    finally:
        stop_event.set()
        await asyncio.gather(heartbeat_task, return_exceptions=True)


async def _run_analysis_background_impl(
    *,
    run_id: UUID,
    business: Business,
    country: str = "IN",
    state: str | None = None,
    additional_context: str | None = None,
    num_llms: int | None = None,
    run_type: str = "marketing_strategy",
    speed: str = "general",
) -> None:
    """Run the analysis pipeline in the background. Updates the run record
    in `get_default_store()` as it progresses."""
    store: Store = get_default_store()

    def _set(status: str, *, error: str | None = None) -> None:
        try:
            store.update_run_status(run_id, status, error=error)  # type: ignore[arg-type]
        except Exception as exc:
            log.warning("runner.set_status.failed", run_id=str(run_id), error=str(exc))

    log.info("runner.analyze.start", run_id=str(run_id), url=business.url)
    council = _pick_council(num_llms, speed=speed)
    if council is None:
        _set("failed", error="No LLM API keys available — set at least one vendor key in .env.")
        return

    # 1. Crawl + Google Web Search + Additional Context + Bridged Daily Research context.
    _set("ingesting")
    artifacts = await _try_crawl(business.url, business.tenant_id, business.id)

    # Gathers real-time national & international news/government policies
    search_artifacts = await _fetch_google_search_artifacts(business, country, state)
    artifacts.extend(search_artifacts)

    # Find latest completed daily research run for this business to bridge findings
    daily_research_run = None
    if run_type == "marketing_strategy":
        try:
            from bizpulse.models import DailyResearchReport
            all_runs = store.list_runs_for_business(business.id)
            for r in all_runs:
                if r.run_type == "daily_research" and r.status == "complete" and r.final_output:
                    daily_research_run = r
                    break
        except Exception as exc:
            log.warning("runner.fetch_daily_research.failed", error=str(exc))

    if daily_research_run and isinstance(daily_research_run.final_output, DailyResearchReport):
        report: DailyResearchReport = daily_research_run.final_output
        intel_parts = [
            f"BizPulse Daily Research Report for {business.url} in {business.industry or 'industry'}",
            f"Most Important Update: {report.most_important_update}",
        ]
        if report.academic_research:
            intel_parts.append("\n--- Academic & Technological Innovations ---")
            for paper in report.academic_research:
                intel_parts.append(f"- Title: {paper.title}\n  Key Findings: {paper.key_findings}\n  Business Application: {paper.business_application}")
        pol = report.policy_and_politics
        if pol.regulatory or pol.financial or pol.geopolitical:
            intel_parts.append("\n--- Regulatory, Policy, and Geopolitical Updates ---")
            if pol.regulatory:
                intel_parts.append("Regulatory Changes:")
                for reg in pol.regulatory:
                    intel_parts.append(f"  - {reg}")
            if pol.financial:
                intel_parts.append("Financial & Budget shifts:")
                for fin in pol.financial:
                    intel_parts.append(f"  - {fin}")
            if pol.geopolitical:
                intel_parts.append("Geopolitical & Trade updates:")
                for geo in pol.geopolitical:
                    intel_parts.append(f"  - {geo}")
        if report.business_deals:
            intel_parts.append("\n--- Strategic Business Deals & Investments ---")
            for deal in report.business_deals:
                intel_parts.append(f"- Entities: {deal.entities}\n  Strategic Impact: {deal.strategic_impact}")
        cli = report.climate_and_weather
        if cli.threats or cli.opportunities:
            intel_parts.append("\n--- Climate & Environmental Matrix ---")
            if cli.threats:
                intel_parts.append("Threats:")
                for t in cli.threats:
                    intel_parts.append(f"  - {t}")
            if cli.opportunities:
                intel_parts.append("Opportunities:")
                for o in cli.opportunities:
                    intel_parts.append(f"  - {o}")
        comp = report.competitors_and_products
        if comp.new_products or comp.competitor_moves or comp.client_sentiment:
            intel_parts.append("\n--- Competitor Intelligence & Sentiment ---")
            if comp.new_products:
                intel_parts.append("New Product Launches:")
                for np in comp.new_products:
                    intel_parts.append(f"  - {np}")
            if comp.competitor_moves:
                intel_parts.append("Competitor Moves & Pivots:")
                for m in comp.competitor_moves:
                    intel_parts.append(f"  - {m}")
            if comp.client_sentiment:
                intel_parts.append("Client Sentiment & Demand:")
                for s in comp.client_sentiment:
                    intel_parts.append(f"  - {s}")
        if report.emerging_radar:
            intel_parts.append("\n--- Emerging Radar Anomaly Signals ---")
            for ra in report.emerging_radar:
                intel_parts.append(f"- {ra}")
        
        intel_text = "\n".join(intel_parts)
        artifacts.append(
            RawArtifact(
                tenant_id=business.tenant_id,
                business_id=business.id,
                source_url=f"daily-research-report-{daily_research_run.id}",
                source_type="user_context",
                content_hash=RawArtifact.hash_text(intel_text),
                extracted_text=intel_text,
            )
        )

    if additional_context:
        artifacts.append(_user_context_artifact(business, additional_context))
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
    except Exception as exc:
        log.warning("runner.ingest.failed", error=str(exc)[:300])
        _set("failed", error=f"ingest failed: {exc}")
        return

    # 3. Run the LangGraph (with retry on transient failures).
    _set("analyzing")
    runner = AgentRunner(
        retrieval=RetrievalEngine(repo, embedder=embedder),  # type: ignore[arg-type]
        council=council,
        industry=business.industry,
    )
    # Run in parallel if we are on local Ollama, else sequential for free-tier safety
    # (keeps us at <= 1 in-flight LLM call across the whole run for API limits).
    is_local = "11434" in settings.llm_base_url or "8800" in settings.llm_base_url
    seq = not is_local
    if run_type == "daily_research":
        from bizpulse.agents.research_graph import build_research_graph

        graph = build_research_graph(runner, sequential=seq)
    else:
        graph = build_analysis_graph(runner, sequential=seq)

    # Fetch up to 2 successful completed runs in the same industry to guide in-context learning
    few_shots = None
    try:
        past_runs = store.get_successful_runs_by_industry(business.industry or "fintech", limit=1)
        few_shots = [pr.final_output for pr in past_runs if pr.final_output]
    except Exception as exc:
        log.warning("runner.few_shots.failed", error=str(exc))

    initial_state = {
        "run_id": run_id,
        "tenant_id": business.tenant_id,
        "business_id": business.id,
        "industry": business.industry or "fintech",
        "business_url": business.url,
        "country": country,
        "state": state,
        "few_shots": few_shots,
        "run_type": run_type,
        "speed": speed,
    }
    try:
        final = await _invoke_graph_with_retry(graph, initial_state)
    except Exception as exc:
        log.warning("runner.graph.failed", error=str(exc)[:300])
        _set("failed", error=f"graph invocation failed: {exc}")
        return

    if run_type == "daily_research":
        strategy = final.get("research_report")
    else:
        strategy = final.get("final_strategy")
        if strategy and daily_research_run and isinstance(daily_research_run.final_output, DailyResearchReport):
            report = daily_research_run.final_output
            try:
                strategy = strategy.model_copy(
                    update={
                        "research_and_innovation": [p.model_dump() for p in report.academic_research],
                        "policy_and_politics": report.policy_and_politics.model_dump(),
                        "business_deals": [d.model_dump() for d in report.business_deals],
                        "climate_and_weather": report.climate_and_weather.model_dump(),
                        "competitors_and_products": report.competitors_and_products.model_dump(),
                        "emerging_radar": report.emerging_radar,
                    }
                )
            except Exception as exc:
                log.warning("runner.populate_bridge_fields.failed", error=str(exc))
    compliance = final.get("compliance_report")

    if strategy is None:
        errors = final.get("errors", [])
        _set("failed", error="; ".join(errors)[:500] or "no output produced")
        return

    # 4. Attach compliance + agent_traces to the strategy + persist.
    traces = final.get("agent_traces") or []
    try:
        update_fields = {"agent_traces": traces}
        if hasattr(strategy, "compliance_report"):
            update_fields["compliance_report"] = compliance
        strategy = strategy.model_copy(update=update_fields)
    except Exception as exc:
        log.warning("runner.merge_failed", error=str(exc)[:200])

    _persist_final_output(store=store, run_id=run_id, strategy=strategy)
    # Persist cost / token totals from the runner's accumulators.
    try:
        store.update_run_usage(  # type: ignore[arg-type]
            run_id,
            cost_usd=runner.cumulative_cost_usd,
            input_tokens=runner.cumulative_input_tokens,
            output_tokens=runner.cumulative_output_tokens,
            llm_calls=runner.cumulative_llm_calls,
        )
    except Exception as exc:
        log.warning("runner.usage.persist_failed", error=str(exc)[:200])
    _set("complete")
    log.info(
        "runner.analyze.complete",
        run_id=str(run_id),
        cost_usd=round(runner.cumulative_cost_usd, 6),
        llm_calls=runner.cumulative_llm_calls,
    )


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
    except Exception as exc:
        log.warning("runner.persist.failed", error=str(exc)[:200])
