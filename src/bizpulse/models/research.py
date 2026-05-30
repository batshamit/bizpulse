"""Daily research report schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from bizpulse.models.agents import AgentTrace
from bizpulse.models.citations import Citation
from bizpulse.models.common import BusinessId, StrictModel, TenantId


class AcademicPaper(StrictModel):
    """Detailed item for the Academic worker output."""
    title: str = Field(min_length=1, description="Title of the paper or study.")
    key_findings: str = Field(min_length=1, description="Primary technical or methodology findings.")
    business_application: str = Field(min_length=1, description="One-sentence action-ready application for our business.")


class BusinessDeal(StrictModel):
    """Detailed item for the Market Scout worker output."""
    entities: str = Field(min_length=1, description="The key companies, competitors, or startups involved in the deal.")
    strategic_impact: str = Field(min_length=1, description="Strategic significance or market implication of this M&A/partnership/funding.")


class AcademicTrackerOutput(StrictModel):
    """Output for Worker 1: The Academic (Research & Innovation)."""
    papers: list[AcademicPaper] = Field(default_factory=list, description="Bulleted list of new papers/studies.")
    citations: list[Citation] = Field(default_factory=list)


class PolicyAnalystOutput(StrictModel):
    """Output for Worker 2: The Policy Analyst (Gov, Budget & Geo-Politics)."""
    regulatory: list[str] = Field(default_factory=list, description="Regulatory changes affecting the sector.")
    financial: list[str] = Field(default_factory=list, description="New budget allocations, subsidies, interest-rates.")
    geopolitical: list[str] = Field(default_factory=list, description="International trade or geopolitical shifts.")
    citations: list[Citation] = Field(default_factory=list)


class MarketScoutOutput(StrictModel):
    """Output for Worker 3: The Market Scout (Business Insights & Deals)."""
    deals: list[BusinessDeal] = Field(default_factory=list, description="Strategic M&A, funding rounds, strategic partnerships, and expansions.")
    citations: list[Citation] = Field(default_factory=list)


class EnvironmentalMonitorOutput(StrictModel):
    """Output for Worker 4: The Environmental Monitor (Climate & Weather)."""
    threats: list[str] = Field(default_factory=list, description="Climate or weather risks to operations, yield, or supply chains.")
    opportunities: list[str] = Field(default_factory=list, description="New operational or sustainability opportunities arising from environment changes.")
    citations: list[Citation] = Field(default_factory=list)


class CompetitiveIntelligenceOutput(StrictModel):
    """Output for Worker 5: The Competitive Intelligence Agent (Competitors & Products)."""
    new_products: list[str] = Field(default_factory=list, description="New product specifications, features, or pricing shifts.")
    competitor_moves: list[str] = Field(default_factory=list, description="Strategic competitor announcements, launches, or pivots.")
    client_sentiment: list[str] = Field(default_factory=list, description="Client feedback, demands, or market-need trends.")
    citations: list[Citation] = Field(default_factory=list)


class RadarOutput(StrictModel):
    """Output for Worker 6: The Radar Agent (Other/Emerging Updates)."""
    anomalies: list[str] = Field(default_factory=list, description="Top 3 miscellaneous but critical anomalies, adjacent trends, or local events.")
    citations: list[Citation] = Field(default_factory=list)


class DailyResearchReport(StrictModel):
    """Synthesized Daily Research Report for a domain."""

    tenant_id: TenantId
    business_id: BusinessId
    industry: str
    run_type: Literal["daily_research"] = "daily_research"
    most_important_update: str = Field(
        min_length=1,
        description="The most critical update/takeaway positioned at the very top (executive_highlight).",
    )
    academic_research: list[AcademicPaper] = Field(
        default_factory=list,
        description="Workers 1 findings: academic and technological breakthroughs.",
    )
    policy_and_politics: PolicyAnalystOutput = Field(
        default_factory=PolicyAnalystOutput,
        description="Worker 2 findings: regulatory, financial, and geopolitical shifts.",
    )
    business_deals: list[BusinessDeal] = Field(
        default_factory=list,
        description="Worker 3 findings: strategic M&A, funding, and partnerships.",
    )
    climate_and_weather: EnvironmentalMonitorOutput = Field(
        default_factory=EnvironmentalMonitorOutput,
        description="Worker 4 findings: weather events or long-term climate risk threat/opportunity matrix.",
    )
    competitors_and_products: CompetitiveIntelligenceOutput = Field(
        default_factory=CompetitiveIntelligenceOutput,
        description="Worker 5 findings: competitor moves, pricing shifts, and client sentiment.",
    )
    emerging_radar: list[str] = Field(
        default_factory=list,
        description="Worker 6 findings: anomalies, adjacent industry trends, or localized emerging events.",
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
