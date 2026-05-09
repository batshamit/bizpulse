"""Per-agent node factories for the LangGraph state graph.

Each `make_*_node(runner)` returns an async function `(state) -> partial_state`
that langgraph can register via `graph.add_node(name, fn)`. The runner is
captured in the closure so nodes don't need a global / context lookup.

Node responsibilities:
  - call AgentRunner.run() with the right schema + query text
  - on AgentRunError, append to `errors` and leave its slot None so the
    Strategist can degrade gracefully
  - record repair attempts in `repair_attempts`
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from bizpulse.agents.runner import AgentRunError, AgentRunner
from bizpulse.agents.state import AnalysisState
from bizpulse.logging import get_logger
from bizpulse.models import (
    AudienceAnalysis,
    BrandAnalysis,
    CompetitiveLandscape,
    ContentAudit,
    MarketingStrategy,
)

log = get_logger(__name__)

NodeFn = Callable[[AnalysisState], Awaitable[dict[str, object]]]


def _record_repair(state_update: dict, agent: str, repaired: bool) -> dict:
    if repaired:
        state_update["repair_attempts"] = [agent]
    return state_update


# ---- analytical nodes ----------------------------------------------------

def make_brand_node(runner: AgentRunner) -> NodeFn:
    async def brand(state: AnalysisState) -> dict[str, object]:
        try:
            r = await runner.run(
                agent="brand_analyst",
                task="Extract this business's brand positioning, tone, and 3 distinct value propositions. Cite chunk_ids.",
                output_schema=BrandAnalysis,
                query_text="brand positioning tone value propositions",
            )
            return _record_repair({"brand": r.output}, "brand_analyst", r.repair_attempted)
        except AgentRunError as exc:
            log.warning("graph.brand.failed", error=str(exc)[:300])
            return {"brand": None, "errors": [f"brand_analyst: {exc}"]}
    return brand


def make_audience_node(runner: AgentRunner) -> NodeFn:
    async def audience(state: AnalysisState) -> dict[str, object]:
        try:
            r = await runner.run(
                agent="audience_analyst",
                task="Identify the primary ICP (ideal customer profile) and any meaningful secondary personas. Cite chunk_ids that support each motivation and pain point.",
                output_schema=AudienceAnalysis,
                query_text="customer audience persona demographics pain points",
            )
            return _record_repair({"audience": r.output}, "audience_analyst", r.repair_attempted)
        except AgentRunError as exc:
            log.warning("graph.audience.failed", error=str(exc)[:300])
            return {"audience": None, "errors": [f"audience_analyst: {exc}"]}
    return audience


def make_competitor_node(runner: AgentRunner) -> NodeFn:
    async def competitor(state: AnalysisState) -> dict[str, object]:
        try:
            r = await runner.run(
                agent="competitor_scout",
                task="Identify 3-5 competitors. For each: name, url, positioning, strengths, weaknesses. Set verified=true ONLY for competitors confirmed via independent web search; otherwise omit. No fabrication.",
                output_schema=CompetitiveLandscape,
                query_text="competitors market position alternatives",
            )
            return _record_repair({"competitive_landscape": r.output}, "competitor_scout", r.repair_attempted)
        except AgentRunError as exc:
            log.warning("graph.competitor.failed", error=str(exc)[:300])
            return {"competitive_landscape": None, "errors": [f"competitor_scout: {exc}"]}
    return competitor


def make_content_node(runner: AgentRunner) -> NodeFn:
    async def content(state: AnalysisState) -> dict[str, object]:
        try:
            r = await runner.run(
                agent="content_auditor",
                task="Audit the business's marketing content. List specific findings with evidence + suggested fix. Identify which content pillars are strong vs weak.",
                output_schema=ContentAudit,
                query_text="content marketing pillars blog social media engagement",
            )
            return _record_repair({"content_audit": r.output}, "content_auditor", r.repair_attempted)
        except AgentRunError as exc:
            log.warning("graph.content.failed", error=str(exc)[:300])
            return {"content_audit": None, "errors": [f"content_auditor: {exc}"]}
    return content


def make_strategist_node(runner: AgentRunner) -> NodeFn:
    """Synthesizes prior agent outputs into the final MarketingStrategy.

    The strategist sees the prior outputs via the user prompt task description
    so it can incorporate them. The retrieved chunks remain available as
    citation evidence.
    """

    async def strategist(state: AnalysisState) -> dict[str, object]:
        prior = _summarize_prior(state)
        try:
            r = await runner.run(
                agent="strategist",
                task=(
                    "Synthesize the prior agent outputs into a complete MarketingStrategy. "
                    "Every Recommendation MUST cite chunk_ids. Lift citations from the prior "
                    "agent outputs where appropriate. Aim for 3-7 prioritized recommendations "
                    "across the most relevant channels for this industry.\n\n"
                    f"Prior outputs (verbatim):\n{prior}"
                ),
                output_schema=MarketingStrategy,
                query_text="marketing strategy recommendations channels priorities",
                top_k=12,
            )
            return _record_repair(
                {"final_strategy": r.output},
                "strategist",
                r.repair_attempted,
            )
        except AgentRunError as exc:
            log.warning("graph.strategist.failed", error=str(exc)[:300])
            return {"final_strategy": None, "errors": [f"strategist: {exc}"]}
    return strategist


# ---- helpers -------------------------------------------------------------

def _summarize_prior(state: AnalysisState) -> str:
    """Build a compact text block summarizing whatever prior agent outputs
    are present, so the strategist can synthesize without re-running them."""
    parts = []
    if (b := state.get("brand")) is not None:
        parts.append(f"Brand: {b.model_dump_json()}")
    if (a := state.get("audience")) is not None:
        parts.append(f"Audience: {a.model_dump_json()}")
    if (c := state.get("competitive_landscape")) is not None:
        parts.append(f"Competitive Landscape: {c.model_dump_json()}")
    if (cau := state.get("content_audit")) is not None:
        parts.append(f"Content Audit: {cau.model_dump_json()}")
    if not parts:
        return "(no prior agent outputs available — answer from retrieval alone)"
    return "\n\n".join(parts)
