"""Daily research report schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from bizpulse.models.agents import AgentTrace
from bizpulse.models.citations import Citation
from bizpulse.models.common import BusinessId, StrictModel, TenantId


class ProjectTrackerOutput(StrictModel):
    """Output for the project/entities tracker sub-agent."""

    new_launches: list[str] = Field(
        default_factory=list,
        description="Gathers new project/product launches in popular areas.",
    )
    price_movements: list[str] = Field(
        default_factory=list,
        description="Gathers price-per-sqft or metric value movement in key localities.",
    )
    uncertain_claims: list[str] = Field(
        default_factory=list,
        description="Explicit log of claims/numbers with high uncertainty.",
    )
    citations: list[Citation] = Field(default_factory=list)


class PolicyTrackerOutput(StrictModel):
    """Output for the policy/regulations tracker sub-agent."""

    policy_updates: list[str] = Field(
        default_factory=list,
        description="Gathers policy/interest-rate/regulatory updates affecting the domain.",
    )
    market_updates: list[str] = Field(
        default_factory=list,
        description="Gathers market news or trends affecting buyers/users.",
    )
    uncertain_claims: list[str] = Field(
        default_factory=list,
        description="Explicit log of claims/news with high uncertainty.",
    )
    citations: list[Citation] = Field(default_factory=list)


class DailyResearchReport(StrictModel):
    """Synthesized Daily Research Report for a domain."""

    tenant_id: TenantId
    business_id: BusinessId
    industry: str
    run_type: Literal["daily_research"] = "daily_research"
    most_important_update: str = Field(
        min_length=1,
        description="The most critical update/takeaway positioned at the very top.",
    )
    market_and_entities: list[str] = Field(
        default_factory=list,
        description="Short plain-language bullets summarizing entities & metrics launches.",
    )
    policy_and_news: list[str] = Field(
        default_factory=list,
        description="Short plain-language bullets summarizing regulations/policy updates.",
    )
    uncertainty_log: list[str] = Field(
        default_factory=list,
        description="Explicit log of numbers, rates, or dates that couldn't be fully verified or have uncertainty.",
    )
    overall_confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Overall confidence score for the synthesized report.",
    )
    citations: list[Citation] = Field(default_factory=list)
    agent_traces: list[AgentTrace] = Field(default_factory=list)
