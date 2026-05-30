"""State for the multi-agent LangGraph pipeline.

`AnalysisState` is what flows through the graph. Each node receives the
current state and returns a dict of *partial* updates, which langgraph
merges into the running state.
"""

from __future__ import annotations

from typing import Annotated, TypedDict
from uuid import UUID

from bizpulse.models import (
    AcademicTrackerOutput,
    PolicyAnalystOutput,
    MarketScoutOutput,
    EnvironmentalMonitorOutput,
    CompetitiveIntelligenceOutput,
    RadarOutput,
    AudienceAnalysis,
    BrandAnalysis,
    CompetitiveLandscape,
    ContentAudit,
    DailyResearchReport,
    MarketingStrategy,
)
from bizpulse.models.agents import AgentTrace
from bizpulse.models.compliance import ComplianceReport


def _append(left: list, right: list) -> list:
    """Reducer: state updates that re-write the same key concat instead of overwrite."""
    return list(left) + list(right)


class AnalysisState(TypedDict, total=False):
    """Flowing state for one BusinessAnalysis run."""

    # ---- inputs (set at graph entry) ----
    run_id: UUID
    tenant_id: UUID
    business_id: UUID
    industry: str
    business_url: str
    country: str
    """ISO 3166-1 alpha-2; default 'IN' if absent."""
    state: str | None
    """State/province slug for state-specific regulators (e.g., 'maharashtra')."""
    few_shots: list[MarketingStrategy] | None
    """Successful historical strategies for the same industry to guide in-context learning."""
    run_type: str
    """Type of run: 'marketing_strategy' or 'daily_research'."""
    speed: str
    """Speed mode: 'general' (local-first) or 'ultra_fast' (cloud-first)."""

    # ---- per-agent outputs (each node fills its slot) ----
    brand: BrandAnalysis | None
    audience: AudienceAnalysis | None
    competitive_landscape: CompetitiveLandscape | None
    content_audit: ContentAudit | None

    # ---- research per-agent outputs ----
    academic_tracker: AcademicTrackerOutput | None
    policy_analyst: PolicyAnalystOutput | None
    market_scout: MarketScoutOutput | None
    environmental_monitor: EnvironmentalMonitorOutput | None
    competitive_intelligence: CompetitiveIntelligenceOutput | None
    radar: RadarOutput | None

    # ---- final synthesis ----
    final_strategy: MarketingStrategy | None
    research_report: DailyResearchReport | None

    # ---- compliance audit (added by compliance_checker after strategist) ----
    compliance_report: ComplianceReport | None

    # ---- audit trail / failures ----
    errors: Annotated[list[str], _append]
    """Per-node errors; nodes that fail append to this and let downstream
    nodes decide whether to proceed or short-circuit."""

    repair_attempts: Annotated[list[str], _append]
    """Names of agents that needed a JSON-repair pass — useful in the
    Critic decision and the demo audit log."""

    agent_traces: Annotated[list[AgentTrace], _append]
    """Per-node trace — every analyst + strategist + compliance node
    appends one AgentTrace before returning. Persisted into
    MarketingStrategy.agent_traces so the GUI can render the 'Agents' tab."""
