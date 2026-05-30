"""LangGraph state-graph for the Lead Intelligence Orchestrator (Daily Research) pipeline."""

from __future__ import annotations

from typing import Any

from bizpulse.agents.research_nodes import (
    make_academic_tracker_node,
    make_policy_analyst_node,
    make_market_scout_node,
    make_environmental_monitor_node,
    make_competitive_intelligence_node,
    make_radar_node,
    make_research_synthesizer_node,
)
from bizpulse.agents.runner import AgentRunner
from bizpulse.agents.state import AnalysisState


def build_research_graph(
    runner: AgentRunner,
    *,
    sequential: bool = False,
) -> Any:
    """Return a compiled langgraph graph that runs the research sub-agents.

    If `sequential=True`, we chain the tracker nodes to run one after another,
    which is safer for free-tier LLM rate limits or resource constraints.
    """
    from langgraph.graph import END, START, StateGraph

    g = StateGraph(AnalysisState)

    # Register the 6 specialized data-gathering nodes
    g.add_node("academic_tracker", make_academic_tracker_node(runner))
    g.add_node("policy_analyst", make_policy_analyst_node(runner))
    g.add_node("market_scout", make_market_scout_node(runner))
    g.add_node("environmental_monitor", make_environmental_monitor_node(runner))
    g.add_node("competitive_intelligence", make_competitive_intelligence_node(runner))
    g.add_node("radar", make_radar_node(runner))
    g.add_node("research_synthesizer", make_research_synthesizer_node(runner))

    if sequential:
        # Chain sequentially to avoid parallel LLM queries/VRAM pressure
        g.add_edge(START, "academic_tracker")
        g.add_edge("academic_tracker", "policy_analyst")
        g.add_edge("policy_analyst", "market_scout")
        g.add_edge("market_scout", "environmental_monitor")
        g.add_edge("environmental_monitor", "competitive_intelligence")
        g.add_edge("competitive_intelligence", "radar")
        g.add_edge("radar", "research_synthesizer")
    else:
        # Run sub-agents in parallel
        g.add_edge(START, "academic_tracker")
        g.add_edge(START, "policy_analyst")
        g.add_edge(START, "market_scout")
        g.add_edge(START, "environmental_monitor")
        g.add_edge(START, "competitive_intelligence")
        g.add_edge(START, "radar")

        g.add_edge("academic_tracker", "research_synthesizer")
        g.add_edge("policy_analyst", "research_synthesizer")
        g.add_edge("market_scout", "research_synthesizer")
        g.add_edge("environmental_monitor", "research_synthesizer")
        g.add_edge("competitive_intelligence", "research_synthesizer")
        g.add_edge("radar", "research_synthesizer")

    g.add_edge("research_synthesizer", END)

    return g.compile()
