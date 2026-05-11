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

import time

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
from bizpulse.models.agents import AgentTrace
from bizpulse.models.common import utcnow

log = get_logger(__name__)

NodeFn = Callable[[AnalysisState], Awaitable[dict[str, object]]]


def _record_repair(state_update: dict, agent: str, repaired: bool) -> dict:
    if repaired:
        state_update["repair_attempts"] = [agent]
    return state_update


def _trace(
    *,
    agent: str,
    started_ms: float,
    status: str,
    error: str | None = None,
    retries: int = 0,
) -> AgentTrace:
    """Build an AgentTrace from common kwargs. duration_ms is computed from
    time.perf_counter() handles passed in `started_ms`."""
    duration_ms = max(0.0, (time.perf_counter() - started_ms) * 1000.0)
    return AgentTrace(
        agent=agent,  # type: ignore[arg-type]
        started_at=utcnow(),
        finished_at=utcnow(),
        duration_ms=duration_ms,
        prompt="",  # we don't capture the prompt here; agent_runner already logs it
        response="",
        retries=retries,
        status=status,  # type: ignore[arg-type]
        error=error,
    )


def _node_wrap(agent_name, fn):
    """Decorator-style helper: invoke node-fn and tack on an AgentTrace
    based on whether the result has 'errors' for this agent."""

    async def wrapped(state):
        t0 = time.perf_counter()
        try:
            result = await fn(state)
        except Exception as exc:  # noqa: BLE001 — node bodies catch their own
            result = {"errors": [f"{agent_name}: {exc}"]}
        trace = _trace(
            agent=agent_name,
            started_ms=t0,
            status="failed" if (result.get("errors") and any(agent_name in e for e in result["errors"])) else "ok",
            error=None,
            retries=1 if state.get("repair_attempts") and agent_name in state.get("repair_attempts", []) else 0,
        )
        # Detect a failed-agent error embedded in this update.
        for e in result.get("errors", []) or []:
            if isinstance(e, str) and e.startswith(agent_name + ":"):
                trace = trace.model_copy(update={"status": "failed", "error": e[:300]})
                break
        result.setdefault("agent_traces", []).append(trace)
        return result
    return wrapped


# ---- analytical nodes ----------------------------------------------------

def _make_analyst(
    *,
    agent_name: str,
    task: str,
    query_text: str,
    output_schema,
    state_key: str,
):
    """Common scaffolding for an analyst node: run the agent, record a
    trace, surface failure as state['errors'] without raising."""

    def factory(runner: AgentRunner) -> NodeFn:
        async def node(state: AnalysisState) -> dict[str, object]:
            t0 = time.perf_counter()
            try:
                r = await runner.run(
                    agent=agent_name,  # type: ignore[arg-type]
                    task=task,
                    output_schema=output_schema,
                    query_text=query_text,
                )
                trace = _trace(
                    agent=agent_name,
                    started_ms=t0,
                    status="ok",
                    retries=1 if r.repair_attempted else 0,
                )
                update = _record_repair(
                    {state_key: r.output, "agent_traces": [trace]},
                    agent_name,
                    r.repair_attempted,
                )
                return update
            except AgentRunError as exc:
                log.warning(f"graph.{agent_name}.failed", error=str(exc)[:300])
                trace = _trace(
                    agent=agent_name,
                    started_ms=t0,
                    status="failed",
                    error=str(exc)[:300],
                )
                return {
                    state_key: None,
                    "errors": [f"{agent_name}: {exc}"],
                    "agent_traces": [trace],
                }
        return node
    return factory


make_brand_node = _make_analyst(
    agent_name="brand_analyst",
    task=(
        "Extract this business's brand positioning, tone, and 3 distinct "
        "value propositions. Cite chunk_ids. Be SPECIFIC to this exact "
        "business — pull the unique-to-them numbers, names, partner brands, "
        "regulatory licenses, awards, milestones. Generic statements that "
        "could apply to any company in the industry are NOT useful."
    ),
    query_text="brand positioning tone value propositions company milestones",
    output_schema=BrandAnalysis,
    state_key="brand",
)

make_audience_node = _make_analyst(
    agent_name="audience_analyst",
    task=(
        "Identify the primary ICP and meaningful secondary personas. For each, "
        "cite chunk_ids that support the motivations and pain points. Surface "
        "any *under-served* audiences hinted at in the content: late adopters / "
        "newcomers (the LAST customer), minorities or accessibility-needs / "
        "regional users (the LEAST-considered), churned or dormant cohorts (the "
        "LOST), price-sensitive / entry-tier / financial-inclusion segments "
        "(the LOWEST-budget). These will be scored by the compliance checker."
    ),
    query_text="customer audience persona demographics pain points underserved minorities",
    output_schema=AudienceAnalysis,
    state_key="audience",
)

make_competitor_node = _make_analyst(
    agent_name="competitor_scout",
    task=(
        "Identify 3-5 SPECIFIC competitors of this business by name and URL. "
        "Prefer competitors mentioned in the retrieved chunks; only invent "
        "names if they're widely known in the industry. For each: name, url, "
        "positioning, strengths, weaknesses. Set verified=true ONLY when the "
        "competitor was visible in the retrieved context; otherwise leave it "
        "false. No fabrication. Avoid listing the business itself."
    ),
    query_text="competitors market position alternatives mentioned in content",
    output_schema=CompetitiveLandscape,
    state_key="competitive_landscape",
)

make_content_node = _make_analyst(
    agent_name="content_auditor",
    task=(
        "Audit this business's marketing content as it actually exists in the "
        "retrieved chunks. List specific findings with the exact text from the "
        "chunks as evidence + a suggested fix. Identify content pillars that "
        "are strong vs weak. Note any pillars MISSING entirely — especially "
        "accessibility content, vernacular-language content, financial-literacy "
        "content for the bottom tier, win-back content for lapsed users."
    ),
    query_text="content marketing pillars blog social media engagement accessibility",
    output_schema=ContentAudit,
    state_key="content_audit",
)


def make_compliance_node(council) -> NodeFn:
    """Run the compliance_checker against the synthesized strategy."""
    from bizpulse.compliance.checker import run_compliance_check

    async def compliance(state: AnalysisState) -> dict[str, object]:
        t0 = time.perf_counter()
        strategy = state.get("final_strategy")
        if strategy is None:
            log.info("graph.compliance.skipped_no_strategy")
            return {
                "compliance_report": None,
                "agent_traces": [_trace(
                    agent="compliance_checker", started_ms=t0,
                    status="failed", error="skipped: no strategy",
                )],
            }
        country = state.get("country", "IN")
        st = state.get("state")
        try:
            report = await run_compliance_check(
                council=council, strategy=strategy, country=country, state=st,
            )
            return {
                "compliance_report": report,
                "agent_traces": [_trace(agent="compliance_checker", started_ms=t0, status="ok")],
            }
        except Exception as exc:  # noqa: BLE001
            log.warning("graph.compliance.failed", error=str(exc)[:300])
            return {
                "compliance_report": None,
                "errors": [f"compliance_checker: {exc}"],
                "agent_traces": [_trace(
                    agent="compliance_checker", started_ms=t0,
                    status="failed", error=str(exc)[:300],
                )],
            }
    return compliance


def make_strategist_node(runner: AgentRunner) -> NodeFn:
    """Synthesizes prior agent outputs into the final MarketingStrategy.

    The strategist sees a *compact* summary of prior outputs (not the full
    verbatim JSON dump — that ballooned the request past per-vendor token
    ceilings, e.g. Groq's 12K per-request cap). top_k=3 chunks for cite
    grounding; the bulk of substance comes via the prior summaries."""

    async def strategist(state: AnalysisState) -> dict[str, object]:
        prior = _summarize_prior_compact(state)
        t0 = time.perf_counter()
        try:
            r = await runner.run(
                agent="strategist",
                task=(
                    "Produce a SLIM MarketingStrategy specific to THIS business "
                    "(do not output generic industry advice). Required fields:\n"
                    "  - tenant_id, business_id, industry (echo from input)\n"
                    "  - recommendations (3-7 prioritized items)\n"
                    "  - overall_confidence (0..1)\n"
                    "  - summary (3-5 sentence executive overview)\n\n"
                    "Strategy quality bar:\n"
                    "  * Every recommendation MUST reference a specific business "
                    "    detail (a product name, partner, regulatory tier, prior "
                    "    campaign motif, or competitor) lifted from the prior "
                    "    summaries — generic 'post on LinkedIn' won't pass review.\n"
                    "  * At least ONE recommendation should serve an UNDER-served "
                    "    customer segment: late adopters, accessibility-needs / "
                    "    vernacular-language users, lapsed / churned users, or the "
                    "    lowest-budget tier (financial-inclusion / EMI / freemium).\n"
                    "  * Recommendations include channel + specific action + "
                    "    rationale + chunk_id citations from the prior summaries.\n\n"
                    "Set `brand`, `audience`, `competitive_landscape`, `content_audit` "
                    "to null — they're merged from prior outputs after you return.\n\n"
                    f"Prior agent outputs (summarized):\n{prior}"
                ),
                output_schema=MarketingStrategy,
                query_text="marketing strategy recommendations channels priorities",
                top_k=3,
            )
            # Merge the prior analyst outputs back into the strategy so the
            # final report carries the full structure even though the LLM
            # only emitted the synthesis-specific fields. Also normalize
            # `industry` to the canonical slug from state — the LLM
            # sometimes emits the long form ("Financial Technology") which
            # breaks downstream policy lookup keyed on the slug.
            canonical_industry = state.get("industry") or r.output.industry
            merged = r.output.model_copy(update={
                "industry": canonical_industry,
                "brand": state.get("brand") or r.output.brand,
                "audience": state.get("audience") or r.output.audience,
                "competitive_landscape": state.get("competitive_landscape") or r.output.competitive_landscape,
                "content_audit": state.get("content_audit") or r.output.content_audit,
            })
            trace = _trace(
                agent="strategist", started_ms=t0,
                status="ok",
                retries=1 if r.repair_attempted else 0,
            )
            return _record_repair(
                {"final_strategy": merged, "agent_traces": [trace]},
                "strategist",
                r.repair_attempted,
            )
        except AgentRunError as exc:
            log.warning("graph.strategist.failed", error=str(exc)[:300])
            return {
                "final_strategy": None,
                "errors": [f"strategist: {exc}"],
                "agent_traces": [_trace(
                    agent="strategist", started_ms=t0,
                    status="failed", error=str(exc)[:300],
                )],
            }
    return strategist


# ---- helpers -------------------------------------------------------------

def _summarize_prior_compact(state: AnalysisState) -> str:
    """Tight text summary of prior agent outputs — designed to fit even a
    Groq 12K-token-per-request ceiling.

    Strategy:
      - keep narrative fields (positioning, tone, value props, primary persona)
      - keep recommendation channels + actions (the reasoning seeds)
      - drop full Citation dumps; surface chunk_ids inline as a short list
    """
    parts: list[str] = []

    if (b := state.get("brand")) is not None:
        ids = ",".join(str(c.chunk_id) for c in b.citations[:5])
        parts.append(
            "BRAND:\n"
            f"  positioning: {b.positioning[:240]}\n"
            f"  tone: {b.tone[:120]}\n"
            f"  value_props: {b.value_props[:5]}\n"
            f"  citation chunk ids: [{ids}]"
        )

    if (a := state.get("audience")) is not None:
        ids = ",".join(str(c.chunk_id) for c in a.citations[:5])
        parts.append(
            "AUDIENCE:\n"
            f"  primary: {a.primary.name} — {a.primary.description[:200]}\n"
            f"  motivations: {a.primary.motivations[:5]}\n"
            f"  pain points: {a.primary.pain_points[:5]}\n"
            f"  citation chunk ids: [{ids}]"
        )

    if (c := state.get("competitive_landscape")) is not None:
        names = ", ".join(
            f"{cm.name} ({cm.url})"
            for cm in c.competitors[:5]
        )
        ids = ",".join(str(ci.chunk_id) for ci in c.citations[:5])
        parts.append(
            "COMPETITORS:\n"
            f"  {names}\n"
            f"  market position: {c.market_position[:240]}\n"
            f"  citation chunk ids: [{ids}]"
        )

    if (cau := state.get("content_audit")) is not None:
        strong = ", ".join(cau.pillars_strong[:5]) if cau.pillars_strong else "(none)"
        weak = ", ".join(cau.pillars_weak[:5]) if cau.pillars_weak else "(none)"
        finds = "; ".join(f.observation[:120] for f in cau.findings[:4])
        parts.append(
            "CONTENT AUDIT:\n"
            f"  strong pillars: {strong}\n"
            f"  weak pillars: {weak}\n"
            f"  top findings: {finds}"
        )

    if not parts:
        return "(no prior agent outputs available — answer from retrieval alone)"
    return "\n\n".join(parts)
