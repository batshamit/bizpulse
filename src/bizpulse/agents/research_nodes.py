"""Per-agent node factories for the Daily Research Agent pipeline."""

from __future__ import annotations

import time
from typing import Any

from bizpulse.agents.runner import AgentRunner
from bizpulse.agents.state import AnalysisState
from bizpulse.logging import get_logger

log = get_logger(__name__)

NodeFn = Any


def make_project_tracker_node(runner: AgentRunner) -> NodeFn:
    """Sub-agent node that gathers entities launches and metric trends from the domain ontology."""

    async def node(state: AnalysisState) -> dict[str, object]:
        from bizpulse.agents.nodes import _record_repair, _trace
        from bizpulse.models import ProjectTrackerOutput, load_industry

        t0 = time.perf_counter()
        agent_name = "project_tracker"
        state_key = "project_tracker"

        # Load the domain Pack dynamically
        industry_slug = state.get("industry") or "real_estate"
        pack = load_industry(industry_slug)

        entities_str = ", ".join(pack.ontology.entities)
        metrics_str = ", ".join(pack.ontology.metrics)
        country = state.get("country") or "IN"
        location_str = f"Country: {country}"
        if state.get("state"):
            location_str += f", State: {state.get('state')}"

        task = (
            f"Act as a market and project tracking agent for the {pack.name} domain for {location_str}.\n"
            f"Identify and gather information on the following entities: {entities_str}.\n"
            f"Identify and gather changes, trends, or movements in the following metrics: {metrics_str}.\n"
            "Cite chunk_ids from the retrieved context. Be ultra-specific and factual.\n"
            "Do not include anything you cannot verify from the context. If a number is uncertain or missing, "
            "place it in the 'uncertain_claims' list rather than stating it as a verified fact."
        )

        query_text = f"new launches project launches price trends price sqft movement {entities_str} {metrics_str}"

        try:
            r = await runner.run(
                agent=agent_name,  # type: ignore[arg-type]
                task=task,
                output_schema=ProjectTrackerOutput,
                query_text=query_text,
                top_k=8,
            )
            trace = _trace(
                agent=agent_name,
                started_ms=t0,
                status="ok",
                retries=1 if r.repair_attempted else 0,
            )
            return _record_repair(
                {state_key: r.output, "agent_traces": [trace]},
                agent_name,
                r.repair_attempted,
            )
        except Exception as exc:
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


def make_policy_tracker_node(runner: AgentRunner) -> NodeFn:
    """Sub-agent node that gathers policy and regulatory updates from the domain ontology."""

    async def node(state: AnalysisState) -> dict[str, object]:
        from bizpulse.agents.nodes import _record_repair, _trace
        from bizpulse.models import PolicyTrackerOutput, load_industry

        t0 = time.perf_counter()
        agent_name = "policy_tracker"
        state_key = "policy_tracker"

        # Load the domain Pack dynamically
        industry_slug = state.get("industry") or "real_estate"
        pack = load_industry(industry_slug)

        regs_str = ", ".join(pack.ontology.regulations)
        country = state.get("country") or "IN"
        location_str = f"Country: {country}"
        if state.get("state"):
            location_str += f", State: {state.get('state')}"

        task = (
            f"Act as a policy and regulations tracking agent for the {pack.name} domain for {location_str}.\n"
            f"Identify and gather policy, regulatory, tax, interest-rate, and market news updates affecting the following: {regs_str}.\n"
            "Cite chunk_ids from the retrieved context. Be ultra-specific and factual.\n"
            "Do not include anything you cannot verify from the context. If a policy change or rate is uncertain or missing, "
            "place it in the 'uncertain_claims' list rather than stating it as a verified fact."
        )

        query_text = f"policy news regulations tax GST RERA interest rates finance rules {regs_str}"

        try:
            r = await runner.run(
                agent=agent_name,  # type: ignore[arg-type]
                task=task,
                output_schema=PolicyTrackerOutput,
                query_text=query_text,
                top_k=8,
            )
            trace = _trace(
                agent=agent_name,
                started_ms=t0,
                status="ok",
                retries=1 if r.repair_attempted else 0,
            )
            return _record_repair(
                {state_key: r.output, "agent_traces": [trace]},
                agent_name,
                r.repair_attempted,
            )
        except Exception as exc:
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


def make_research_synthesizer_node(runner: AgentRunner) -> NodeFn:
    """Orchestrator node that combines trackers findings into a broker-friendly one-page summary."""

    async def node(state: AnalysisState) -> dict[str, object]:
        from bizpulse.agents.nodes import _record_repair, _trace
        from bizpulse.models import DailyResearchReport, load_industry

        t0 = time.perf_counter()
        agent_name = "research_synthesizer"
        state_key = "research_report"

        industry_slug = state.get("industry") or "real_estate"
        pack = load_industry(industry_slug)

        # Retrieve outputs from prior tracker agents
        project_data = state.get("project_tracker")
        policy_data = state.get("policy_tracker")

        # Fallback to empty lists if prior node failed
        p_launches = project_data.new_launches if project_data else []
        p_movements = project_data.price_movements if project_data else []
        p_uncertain = project_data.uncertain_claims if project_data else []

        pol_updates = policy_data.policy_updates if policy_data else []
        pol_market = policy_data.market_updates if policy_data else []
        pol_uncertain = policy_data.uncertain_claims if policy_data else []

        prior_context = (
            f"--- Market & Project Launches ---\n"
            f"New launches: {p_launches}\n"
            f"Price/Metric movements: {p_movements}\n"
            f"Uncertain project claims: {p_uncertain}\n\n"
            f"--- Policy & Regulations ---\n"
            f"Policy updates: {pol_updates}\n"
            f"Market updates: {pol_market}\n"
            f"Uncertain policy claims: {pol_uncertain}\n"
        )

        task = (
            f"Act as the lead synthesis agent for the {pack.name} Daily Research report.\n"
            "Format the final report into a clean, simple executive summary that a non-technical professional "
            "can read in two minutes. Follow these guidelines:\n"
            "  1. Plain language, short bullets.\n"
            "  2. Most important update at the very top (highest priority/impact event).\n"
            "  3. Compile all entity launches and metric movements into 'market_and_entities'.\n"
            "  4. Compile all regulatory, tax, interest-rate, and market sentiment news into 'policy_and_news'.\n"
            "  5. Pull any claims from the prior sub-agents marked as uncertain, or any numbers/dates/rates "
            "     that you find inconsistent or uncertain in the source context, and put them in 'uncertainty_log'. "
            "     If a number or metric is uncertain, you MUST list it in 'uncertainty_log'.\n"
            "  6. Overall confidence score (0..1) reflecting the verified completeness of the report.\n"
            "  7. Provide citations with valid chunk_ids matching the source context.\n\n"
            f"Here are the findings from the sub-agents:\n{prior_context}"
        )

        try:
            r = await runner.run(
                agent=agent_name,  # type: ignore[arg-type]
                task=task,
                output_schema=DailyResearchReport,
                query_text="daily research summary market policy project trends",
                top_k=4,
            )
            trace = _trace(
                agent=agent_name,
                started_ms=t0,
                status="ok",
                retries=1 if r.repair_attempted else 0,
            )
            # Normalise parameters
            canonical_industry = state.get("industry") or r.output.industry
            merged_report = r.output.model_copy(
                update={
                    "tenant_id": state["tenant_id"],
                    "business_id": state["business_id"],
                    "industry": canonical_industry,
                }
            )
            return _record_repair(
                {state_key: merged_report, "agent_traces": [trace]},
                agent_name,
                r.repair_attempted,
            )
        except Exception as exc:
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
