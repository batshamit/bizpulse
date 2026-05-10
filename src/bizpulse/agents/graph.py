"""LangGraph state-graph for the BusinessAnalysis pipeline.

Topology:

    START
      ├──> brand_analyst    ┐
      ├──> audience_analyst │  (parallel; each fills its own state slot)
      ├──> competitor_scout │
      └──> content_auditor  ┘
                  ↓ (join)
            strategist
                  ↓
            compliance_checker     (Phase 12: scores strategy vs. policies)
                  ↓
                 END

Each parallel analyst has an independent state-update key so langgraph
fans out automatically and re-converges before the strategist runs.
The compliance_checker runs after the strategist and writes
`compliance_report` to state. The graph is forgiving — if any node fails,
downstream nodes degrade gracefully (final_strategy may have None inputs,
compliance_report may be None).
"""

from __future__ import annotations

from typing import Any

from bizpulse.agents.council import Council
from bizpulse.agents.nodes import (
    make_audience_node,
    make_brand_node,
    make_competitor_node,
    make_compliance_node,
    make_content_node,
    make_strategist_node,
)
from bizpulse.agents.runner import AgentRunner
from bizpulse.agents.state import AnalysisState


def build_analysis_graph(
    runner: AgentRunner,
    *,
    compliance_council: Council | None = None,
) -> Any:
    """Return a compiled langgraph graph that takes AnalysisState and runs
    the four analyst nodes in parallel, then the strategist, then
    optionally the compliance_checker.

    `compliance_council` defaults to `runner.council` (re-uses the same
    council). Pass a separate one to use cheaper/different vendors for
    compliance checking (e.g., a single Claude call instead of a debate)."""
    # Lazy import — langgraph is heavy and the package should import-clean
    # without it.
    from langgraph.graph import END, START, StateGraph

    g: StateGraph = StateGraph(AnalysisState)

    g.add_node("brand_analyst", make_brand_node(runner))
    g.add_node("audience_analyst", make_audience_node(runner))
    g.add_node("competitor_scout", make_competitor_node(runner))
    g.add_node("content_auditor", make_content_node(runner))
    g.add_node("strategist", make_strategist_node(runner))
    g.add_node("compliance_checker",
               make_compliance_node(compliance_council or runner.council))

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

    # Compliance audit after strategist.
    g.add_edge("strategist", "compliance_checker")
    g.add_edge("compliance_checker", END)

    return g.compile()
