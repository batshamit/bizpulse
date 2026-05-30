"""Per-agent node factories for the Lead Intelligence Orchestrator (Daily Research) pipeline."""

from __future__ import annotations

import time
from typing import Any

from bizpulse.agents.runner import AgentRunner
from bizpulse.agents.state import AnalysisState
from bizpulse.logging import get_logger

log = get_logger(__name__)

NodeFn = Any


def make_academic_tracker_node(runner: AgentRunner) -> NodeFn:
    """Sub-agent node for Worker 1: The Academic (Research & Innovation)."""

    async def node(state: AnalysisState) -> dict[str, object]:
        from bizpulse.agents.nodes import _record_repair, _trace
        from bizpulse.models import AcademicTrackerOutput, load_industry

        t0 = time.perf_counter()
        agent_name = "academic_tracker"
        state_key = "academic_tracker"

        industry_slug = state.get("industry") or "real_estate"
        pack = load_industry(industry_slug)

        entities_str = ", ".join(pack.ontology.entities)
        country = state.get("country") or "IN"
        location_str = f"Country: {country}"
        if state.get("state"):
            location_str += f", State: {state.get('state')}"

        task = (
            f"Act as Worker 1: The Academic (Research & Innovation) for the {pack.name} domain for {location_str}.\n"
            f"Your objective is to identify the latest academic research, technical breakthroughs, or scientific innovations "
            f"applicable to {pack.name}. Scan for papers/studies relating to the following entities: {entities_str}.\n"
            "Cite chunk_ids from the retrieved context. Be ultra-specific and factual.\n"
            "Keep the output extremely structured, fact-based, and under 300 words in total."
        )

        query_text = f"academic research breakthrough technology paper journal preprint science {entities_str}"

        try:
            r = await runner.run(
                agent=agent_name,  # type: ignore[arg-type]
                task=task,
                output_schema=AcademicTrackerOutput,
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


def make_policy_analyst_node(runner: AgentRunner) -> NodeFn:
    """Sub-agent node for Worker 2: The Policy Analyst (Gov, Budget & Geo-Politics)."""

    async def node(state: AnalysisState) -> dict[str, object]:
        from bizpulse.agents.nodes import _record_repair, _trace
        from bizpulse.models import PolicyAnalystOutput, load_industry

        t0 = time.perf_counter()
        agent_name = "policy_analyst"
        state_key = "policy_analyst"

        industry_slug = state.get("industry") or "real_estate"
        pack = load_industry(industry_slug)

        regs_str = ", ".join(pack.ontology.regulations)
        country = state.get("country") or "IN"
        location_str = f"Country: {country}"
        if state.get("state"):
            location_str += f", State: {state.get('state')}"

        task = (
            f"Act as Worker 2: The Policy Analyst (Gov, Budget & Geo-Politics) for the {pack.name} domain for {location_str}.\n"
            f"Your objective is to monitor and identify regulatory updates, policy shifts, tax reforms (like GST), budget allocations, "
            f"subsidies, geo-political/trade updates, or interest-rate changes affecting this sector (e.g., {regs_str}).\n"
            "Cite chunk_ids from the retrieved context. Be ultra-specific and factual.\n"
            "Keep the output extremely structured, fact-based, and under 300 words in total."
        )

        query_text = f"policy regulation tax budget subsidy interest rates geopolitical trade GST RERA {regs_str}"

        try:
            r = await runner.run(
                agent=agent_name,  # type: ignore[arg-type]
                task=task,
                output_schema=PolicyAnalystOutput,
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


def make_market_scout_node(runner: AgentRunner) -> NodeFn:
    """Sub-agent node for Worker 3: The Market Scout (Business Insights & Deals)."""

    async def node(state: AnalysisState) -> dict[str, object]:
        from bizpulse.agents.nodes import _record_repair, _trace
        from bizpulse.models import MarketScoutOutput, load_industry

        t0 = time.perf_counter()
        agent_name = "market_scout"
        state_key = "market_scout"

        industry_slug = state.get("industry") or "real_estate"
        pack = load_industry(industry_slug)

        entities_str = ", ".join(pack.ontology.entities)
        country = state.get("country") or "IN"
        location_str = f"Country: {country}"

        task = (
            f"Act as Worker 3: The Market Scout (Business Insights & Deals) for the {pack.name} domain for {location_str}.\n"
            f"Your objective is to identify and track strategic corporate developments, including mergers and acquisitions (M&A), "
            f"funding rounds, major partnerships, investments, joint ventures, or market expansions related to the industry and entities: {entities_str}.\n"
            "Cite chunk_ids from the retrieved context. Be ultra-specific and factual.\n"
            "Keep the output extremely structured, fact-based, and under 300 words in total."
        )

        query_text = f"M&A merger acquisition funding investment partnership deal venture expansion startup {entities_str}"

        try:
            r = await runner.run(
                agent=agent_name,  # type: ignore[arg-type]
                task=task,
                output_schema=MarketScoutOutput,
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


def make_environmental_monitor_node(runner: AgentRunner) -> NodeFn:
    """Sub-agent node for Worker 4: The Environmental Monitor (Climate & Weather)."""

    async def node(state: AnalysisState) -> dict[str, object]:
        from bizpulse.agents.nodes import _record_repair, _trace
        from bizpulse.models import EnvironmentalMonitorOutput, load_industry

        t0 = time.perf_counter()
        agent_name = "environmental_monitor"
        state_key = "environmental_monitor"

        industry_slug = state.get("industry") or "real_estate"
        pack = load_industry(industry_slug)

        country = state.get("country") or "IN"
        location_str = f"Country: {country}"
        if state.get("state"):
            location_str += f", State: {state.get('state')}"

        task = (
            f"Act as Worker 4: The Environmental Monitor (Climate & Weather) for the {pack.name} domain for {location_str}.\n"
            f"Your objective is to identify environment, climate, weather, or sustainability threats and opportunities affecting this sector. "
            f"Examples: extreme weather risks, ESG mandates, carbon tax impacts, green technology opportunities.\n"
            "Cite chunk_ids from the retrieved context. Be ultra-specific and factual.\n"
            "Keep the output extremely structured, fact-based, and under 300 words in total."
        )

        query_text = f"climate weather ESG sustainability environmental risk green carbon emission natural disaster"

        try:
            r = await runner.run(
                agent=agent_name,  # type: ignore[arg-type]
                task=task,
                output_schema=EnvironmentalMonitorOutput,
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


def make_competitive_intelligence_node(runner: AgentRunner) -> NodeFn:
    """Sub-agent node for Worker 5: The Competitive Intelligence Agent (Competitors & Products)."""

    async def node(state: AnalysisState) -> dict[str, object]:
        from bizpulse.agents.nodes import _record_repair, _trace
        from bizpulse.models import CompetitiveIntelligenceOutput, load_industry

        t0 = time.perf_counter()
        agent_name = "competitive_intelligence"
        state_key = "competitive_intelligence"

        industry_slug = state.get("industry") or "real_estate"
        pack = load_industry(industry_slug)

        entities_str = ", ".join(pack.ontology.entities)
        country = state.get("country") or "IN"
        location_str = f"Country: {country}"

        task = (
            f"Act as Worker 5: The Competitive Intelligence Agent (Competitors & Products) for the {pack.name} domain for {location_str}.\n"
            f"Your objective is to scan for competitor moves, new product announcements/launches/pivots, feature expansions, "
            f"pricing shifts, or client/consumer sentiment changes in the market related to {entities_str}.\n"
            "Cite chunk_ids from the retrieved context. Be ultra-specific and factual.\n"
            "Keep the output extremely structured, fact-based, and under 300 words in total."
        )

        query_text = f"competitor product launch pricing feature brand reputation review feedback sentiment {entities_str}"

        try:
            r = await runner.run(
                agent=agent_name,  # type: ignore[arg-type]
                task=task,
                output_schema=CompetitiveIntelligenceOutput,
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


def make_radar_node(runner: AgentRunner) -> NodeFn:
    """Sub-agent node for Worker 6: The Radar Agent (Other/Emerging Updates)."""

    async def node(state: AnalysisState) -> dict[str, object]:
        from bizpulse.agents.nodes import _record_repair, _trace
        from bizpulse.models import RadarOutput, load_industry

        t0 = time.perf_counter()
        agent_name = "radar"
        state_key = "radar"

        industry_slug = state.get("industry") or "real_estate"
        pack = load_industry(industry_slug)

        country = state.get("country") or "IN"
        location_str = f"Country: {country}"

        task = (
            f"Act as Worker 6: The Radar Agent (Other/Emerging Updates) for the {pack.name} domain for {location_str}.\n"
            f"Your objective is to identify the Top 3 miscellaneous but critical anomalies, adjacent industry trends, "
            f"or localized emerging events that do not fit into other domains but carry strategic significance.\n"
            "Cite chunk_ids from the retrieved context. Be ultra-specific and factual.\n"
            "Keep the output extremely structured, fact-based, and under 300 words in total."
        )

        query_text = f"emerging trends anomalies adjacent industry unexpected events radar local developments new ideas"

        try:
            r = await runner.run(
                agent=agent_name,  # type: ignore[arg-type]
                task=task,
                output_schema=RadarOutput,
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
    """Orchestrator node that combines the 6 workers' findings into a premium Daily Research report."""

    async def node(state: AnalysisState) -> dict[str, object]:
        from bizpulse.agents.nodes import _record_repair, _trace
        from bizpulse.models import DailyResearchReport, load_industry

        t0 = time.perf_counter()
        agent_name = "research_synthesizer"
        state_key = "research_report"

        industry_slug = state.get("industry") or "real_estate"
        pack = load_industry(industry_slug)

        # Retrieve outputs from the 6 worker agents
        academic_data = state.get("academic_tracker")
        policy_data = state.get("policy_analyst")
        market_data = state.get("market_scout")
        environ_data = state.get("environmental_monitor")
        competitive_data = state.get("competitive_intelligence")
        radar_data = state.get("radar")

        # Extract contents or fallbacks
        academic_list = academic_data.papers if academic_data else []
        
        # Policy
        pol_regulatory = policy_data.regulatory if policy_data else []
        pol_financial = policy_data.financial if policy_data else []
        pol_geopolitical = policy_data.geopolitical if policy_data else []
        
        deals_list = market_data.deals if market_data else []
        
        # Environment
        env_threats = environ_data.threats if environ_data else []
        env_opps = environ_data.opportunities if environ_data else []
        
        # Competitor moves & sentiment
        comp_new_products = competitive_data.new_products if competitive_data else []
        comp_moves = competitive_data.competitor_moves if competitive_data else []
        comp_sentiment = competitive_data.client_sentiment if competitive_data else []
        
        radar_anomalies = radar_data.anomalies if radar_data else []

        prior_context = (
            f"--- Worker 1: Academic & Innovation ---\n"
            f"Papers/Studies: {academic_list}\n\n"
            f"--- Worker 2: Policy & Regulations ---\n"
            f"Regulatory: {pol_regulatory}\n"
            f"Financial: {pol_financial}\n"
            f"Geopolitical: {pol_geopolitical}\n\n"
            f"--- Worker 3: Market & Corporate Deals ---\n"
            f"M&A/Partnerships: {deals_list}\n\n"
            f"--- Worker 4: Climate & Environment ---\n"
            f"Threats: {env_threats}\n"
            f"Opportunities: {env_opps}\n\n"
            f"--- Worker 5: Competitors & Products ---\n"
            f"New Products: {comp_new_products}\n"
            f"Competitor Moves: {comp_moves}\n"
            f"Client Sentiment: {comp_sentiment}\n\n"
            f"--- Worker 6: Emerging Radar ---\n"
            f"Anomalies/Radar: {radar_anomalies}\n"
        )

        task = (
            f"Act as the Lead Intelligence Orchestrator for the {pack.name} Daily Research report.\n"
            "Your objective is to compile a comprehensive, premium daily operational brief using the inputs from the 6 specialized data-gathering workers.\n"
            "Format the final report into the unified DailyResearchReport schema. Follow these guidelines:\n"
            "  1. Formulate a single, highly critical 'most_important_update' to place at the very top (executive highlight).\n"
            "  2. Assemble all Worker 1 findings into the academic_research field (list of AcademicPaper).\n"
            "  3. Compile Worker 2 findings into the policy_and_politics field (PolicyAnalystOutput).\n"
            "  4. Compile Worker 3 findings into the business_deals field (list of BusinessDeal).\n"
            "  5. Compile Worker 4 findings into the climate_and_weather field (EnvironmentalMonitorOutput).\n"
            "  6. Compile Worker 5 findings into the competitors_and_products field (CompetitiveIntelligenceOutput).\n"
            "  7. Compile Worker 6 findings into the emerging_radar field (list of strings).\n"
            "  8. Explicitly register any missing, inconsistent, or unverified claims, numbers, rates, or dates in the 'uncertainty_log'.\n"
            "  9. Assign an overall confidence score (0.0 to 1.0) and include valid citations matching the source context.\n\n"
            f"Here are the inputs from the 6 data-gathering sub-agents:\n{prior_context}"
        )

        try:
            r = await runner.run(
                agent=agent_name,  # type: ignore[arg-type]
                task=task,
                output_schema=DailyResearchReport,
                query_text="daily research summary synthesis academic policy deals climate competitors radar",
                top_k=4,
            )
            trace = _trace(
                agent=agent_name,
                started_ms=t0,
                status="ok",
                retries=1 if r.repair_attempted else 0,
            )
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
