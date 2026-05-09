"""LangGraph state-graph for the BusinessAnalysis pipeline.

Topology (Phase 11c — analytical layer; ingestion + critic loop are bolted
on later):

    START
      ├──> brand_analyst    ┐
      ├──> audience_analyst │  (parallel; each fills its own state slot)
      ├──> competitor_scout │
      └──> content_auditor  ┘
                  ↓ (join)
            strategist
                  ↓
                 END

Each parallel node has an independent state-update key so langgraph fans
out automatically and re-converges before the strategist runs.
"""

from __future__ import annotations

from typing import Any

from bizpulse.agents.nodes import (
    make_audience_node,
    make_brand_node,
    make_competitor_node,
    make_content_node,
    make_strategist_node,
)
from bizpulse.agents.runner import AgentRunner
from bizpulse.agents.state import AnalysisState


def build_analysis_graph(runner: AgentRunner) -> Any:
    """Return a compiled langgraph graph that takes AnalysisState and runs
    the four analyst nodes in parallel, then the strategist."""
    # Lazy import — langgraph is heavy and the package should import-clean
    # without it.
    from langgraph.graph import END, START, StateGraph

    g: StateGraph = StateGraph(AnalysisState)

    g.add_node("brand_analyst", make_brand_node(runner))
    g.add_node("audience_analyst", make_audience_node(runner))
    g.add_node("competitor_scout", make_competitor_node(runner))
    g.add_node("content_auditor", make_content_node(runner))
    g.add_node("strategist", make_strategist_node(runner))

    # Fan-out from START.
    g.add_edge(START, "brand_analyst")
    g.add_edge(START, "audience_analyst")
    g.add_edge(START, "competitor_scout")
    g.add_edge(START, "content_auditor")

    # Re-converge at strategist.
    g.add_edge("brand_analyst", "strategist")
    g.add_edge("audience_analyst", "strategist")
    g.add_edge("competitor_scout", "strategist")
    g.add_edge("content_auditor", "strategist")

    g.add_edge("strategist", END)

    return g.compile()
