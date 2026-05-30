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
    sequential: bool = False,
) -> Any:
    """Return a compiled langgraph graph that takes AnalysisState and runs
    the four analyst nodes (parallel by default), then the strategist,
    then the compliance_checker.

    `compliance_council` defaults to `runner.council` (re-uses the same
    council). Pass a separate one to use cheaper/different vendors for
    compliance checking (e.g., a single Claude call instead of a debate).

    `sequential=True` chains the analysts end-to-end so only one LLM call
    is in flight at a time. Necessary for free-tier vendors with low
    parallelism limits (Gemini 5 RPM, Mistral shared pool). Set False when
    you have paid quotas with adequate concurrent throughput."""
    # Lazy import — langgraph is heavy and the package should import-clean
    # without it.
    from langgraph.graph import END, START, StateGraph

    def _realtime_node_wrap(agent_name: str, node_fn: Any) -> Any:
        """Wrap a LangGraph node to update the run status and agent traces in the database in real-time."""
        async def wrapped(state: AnalysisState) -> dict[str, Any]:
            run_id = state.get("run_id")
            
            # 1. On node start: Update database status to this agent_name
            if run_id:
                try:
                    from bizpulse.storage import get_default_store
                    store = get_default_store()
                    if hasattr(store, "update_run_status"):
                        store.update_run_status(run_id, agent_name)  # type: ignore
                except Exception:
                    pass

            # 2. Invoke actual node function
            result = await node_fn(state)

            # 3. On node finish: Append new traces to the database in real-time
            if run_id and isinstance(result, dict):
                traces = result.get("agent_traces") or []
                try:
                    from bizpulse.storage import get_default_store
                    store = get_default_store()
                    if hasattr(store, "add_agent_trace"):
                        for trace in traces:
                            store.add_agent_trace(run_id, agent_name, trace)  # type: ignore
                except Exception:
                    pass
                    
            return result
        return wrapped

    g = StateGraph(AnalysisState)

    g.add_node("brand_analyst", _realtime_node_wrap("brand_analyst", make_brand_node(runner)))
    g.add_node("audience_analyst", _realtime_node_wrap("audience_analyst", make_audience_node(runner)))
    g.add_node("competitor_scout", _realtime_node_wrap("competitor_scout", make_competitor_node(runner)))
    g.add_node("content_auditor", _realtime_node_wrap("content_auditor", make_content_node(runner)))
    g.add_node("strategist", _realtime_node_wrap("strategist", make_strategist_node(runner)))
    g.add_node("compliance_checker", _realtime_node_wrap("compliance_checker", make_compliance_node(compliance_council or runner.council)))

    if sequential:
        # Free-tier-friendly: chain everyone end-to-end so we never have two
        # simultaneous LLM calls on the same vendor.
        g.add_edge(START, "brand_analyst")
        g.add_edge("brand_analyst", "audience_analyst")
        g.add_edge("audience_analyst", "competitor_scout")
        g.add_edge("competitor_scout", "content_auditor")
        g.add_edge("content_auditor", "strategist")
    else:
        # Parallel: 4 analysts fan out from START, re-converge at strategist.
        g.add_edge(START, "brand_analyst")
        g.add_edge(START, "audience_analyst")
        g.add_edge(START, "competitor_scout")
        g.add_edge(START, "content_auditor")
        g.add_edge("brand_analyst", "strategist")
        g.add_edge("audience_analyst", "strategist")
        g.add_edge("competitor_scout", "strategist")
        g.add_edge("content_auditor", "strategist")

    # Compliance audit always last.
    g.add_edge("strategist", "compliance_checker")
    g.add_edge("compliance_checker", END)

    return g.compile()
