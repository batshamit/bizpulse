"""State for the multi-agent LangGraph pipeline.

`AnalysisState` is what flows through the graph. Each node receives the
current state and returns a dict of *partial* updates, which langgraph
merges into the running state.
"""

from __future__ import annotations

from typing import Annotated, TypedDict
from uuid import UUID

from bizpulse.models import (
    AudienceAnalysis,
    BrandAnalysis,
    CompetitiveLandscape,
    ContentAudit,
    MarketingStrategy,
)


def _append(left: list, right: list) -> list:
    """Reducer: state updates that re-write the same key concat instead of overwrite."""
    return list(left) + list(right)


class AnalysisState(TypedDict, total=False):
    """Flowing state for one BusinessAnalysis run."""

    # ---- inputs (set at graph entry) ----
    tenant_id: UUID
    business_id: UUID
    industry: str
    business_url: str

    # ---- per-agent outputs (each node fills its slot) ----
    brand: BrandAnalysis | None
    audience: AudienceAnalysis | None
    competitive_landscape: CompetitiveLandscape | None
    content_audit: ContentAudit | None

    # ---- final synthesis ----
    final_strategy: MarketingStrategy | None

    # ---- audit trail / failures ----
    errors: Annotated[list[str], _append]
    """Per-node errors; nodes that fail append to this and let downstream
    nodes decide whether to proceed or short-circuit."""

    repair_attempts: Annotated[list[str], _append]
    """Names of agents that needed a JSON-repair pass — useful in the
    Critic decision and the demo audit log."""
