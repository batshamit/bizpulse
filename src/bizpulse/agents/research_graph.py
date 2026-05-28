"""LangGraph state-graph for the Daily Research Agent pipeline."""

from __future__ import annotations

from typing import Any

from bizpulse.agents.research_nodes import (
    make_policy_tracker_node,
    make_project_tracker_node,
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
    which is safer for free-tier LLM rate limits.
    """
    from langgraph.graph import END, START, StateGraph

    g = StateGraph(AnalysisState)

    g.add_node("project_tracker", make_project_tracker_node(runner))
    g.add_node("policy_tracker", make_policy_tracker_node(runner))
    g.add_node("research_synthesizer", make_research_synthesizer_node(runner))

    if sequential:
        # Chain sequentially to avoid parallel LLM queries (avoid 429 errors)
        g.add_edge(START, "project_tracker")
        g.add_edge("project_tracker", "policy_tracker")
        g.add_edge("policy_tracker", "research_synthesizer")
    else:
        # Run sub-agents in parallel
        g.add_edge(START, "project_tracker")
        g.add_edge(START, "policy_tracker")
        g.add_edge("project_tracker", "research_synthesizer")
        g.add_edge("policy_tracker", "research_synthesizer")

    g.add_edge("research_synthesizer", END)

    return g.compile()
