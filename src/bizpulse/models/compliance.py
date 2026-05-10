"""Compliance & policy models.

These wire into MarketingStrategy so every report carries a regulatory
audit alongside the marketing recommendations. The 4 L's framework
(Latest / Least / Lost / Lowest) is the headline scoring surface — easy
for an exec to skim, traceable down to per-recommendation flags.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from bizpulse.models.common import StrictModel

PolicySeverity = Literal["info", "advisory", "warning", "violation", "critical"]
"""How serious is non-compliance with this policy?
- info        general FYI
- advisory    nice-to-have / industry best practice
- warning     could attract scrutiny / fine
- violation   triggers known penalty / takedown
- critical    triggers license revocation, criminal liability
"""


class PolicyRef(StrictModel):
    """Static description of one regulatory rule.

    Stored in the policies registry (`bizpulse.compliance.policies`) and
    referenced by slug from agent outputs and ComplianceFlag.
    """

    slug: Annotated[str, Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9_-]*$")]
    body: Annotated[str, Field(min_length=1)]
    """Issuing body — RBI, SEBI, IRDAI, RERA-MH, DPDP, ASCI, FCA, FTC, etc."""

    title: Annotated[str, Field(min_length=1)]
    country: Annotated[str, Field(min_length=2, max_length=3)]
    """ISO 3166-1 alpha-2 (IN, US, GB) or 'EU' for the union."""

    state: str | None = None
    """State / province slug if state-specific (e.g., 'maharashtra', 'karnataka').
    None means national-level."""

    applicable_industries: list[str] = Field(default_factory=list)
    """Industry slugs this policy applies to. Empty list means all industries."""

    severity: PolicySeverity = "warning"
    last_updated: Annotated[str, Field(pattern=r"^\d{4}(-\d{2}(-\d{2})?)?$")]
    """ISO date or year (e.g., '2022', '2023-08', '2024-11-15')."""

    reference_url: str = ""
    summary: Annotated[str, Field(min_length=1)]
    prohibitions: list[str] = Field(default_factory=list)
    """Specific actions a marketer MUST NOT do under this rule."""

    required_disclosures: list[str] = Field(default_factory=list)
    """Specific disclosures that MUST appear if the recommendation triggers this rule."""

    indicative_penalty: str | None = None
    """Human-readable penalty range (e.g., '₹1 lakh per violation', 'license suspension')."""


class ComplianceFlag(StrictModel):
    """One specific concern raised against a Recommendation."""

    policy_slug: Annotated[str, Field(min_length=1)]
    """Must reference a known PolicyRef.slug in the registry."""

    severity: PolicySeverity
    issue: Annotated[str, Field(min_length=1)]
    """One-sentence description of why this recommendation hits this policy."""

    fix: str = ""
    """How to remediate — e.g., 'add disclosure: ...', 'remove guarantee language'."""

    evidence_chunk_ids: list[str] = Field(default_factory=list)
    """Chunks from retrieval that triggered this flag (e.g., the page making the
    suspect claim)."""


class LLLLMetric(StrictModel):
    """The 4 L's headline scoreboard — what the report changes vs. status quo.

    Each metric is in [0, 1] where 1 = best. The narrative one-liner is what
    shows up on the dashboard."""

    latest: float = Field(ge=0.0, le=1.0)
    """Latest — how recent are the regulations this report honors? (1.0 = within
    last 12 months; 0.5 = within 24 months; lower = older)."""

    least: float = Field(ge=0.0, le=1.0)
    """Least — least penalty exposure across the recommendation set
    (1.0 = no critical/violation flags; lower = more exposure)."""

    lost: float = Field(ge=0.0, le=1.0)
    """Lost-revenue avoided — strategies that respect compliance avoid takedowns,
    refunds, churn (1.0 = high avoidance; lower = exposed to losses)."""

    lowest: float = Field(ge=0.0, le=1.0)
    """Lowest cost-of-compliance — measured as overhead added vs. value delivered
    (1.0 = cheap to comply; lower = expensive controls required)."""

    narrative: Annotated[str, Field(min_length=1)]
    """1-3 sentences explaining the scores in plain language."""

    @property
    def average(self) -> float:
        return (self.latest + self.least + self.lost + self.lowest) / 4.0


class CompetitorComplianceCompare(StrictModel):
    """Where do we sit on the compliance spectrum vs. each named competitor."""

    competitor_name: Annotated[str, Field(min_length=1)]
    relative_posture: Literal["weaker", "comparable", "stronger"]
    """Are we 'weaker', 'comparable', or 'stronger' than this competitor on
    regulatory posture overall?"""

    rationale: Annotated[str, Field(min_length=1)]
    evidence_chunk_ids: list[str] = Field(default_factory=list)


class ComplianceReport(StrictModel):
    """Final compliance audit attached to each MarketingStrategy."""

    country: Annotated[str, Field(min_length=2, max_length=3)]
    state: str | None = None
    policies_considered: list[str] = Field(default_factory=list)
    """List of PolicyRef.slug values that were checked."""

    flags: list[ComplianceFlag] = Field(default_factory=list)
    """Per-recommendation issues. Empty = clean report."""

    competitor_compare: list[CompetitorComplianceCompare] = Field(default_factory=list)

    metrics: LLLLMetric

    overall_compliance_score: float = Field(ge=0.0, le=1.0)
    """Roll-up score factoring in flag count + severity. NOT just metrics.average."""

    summary: Annotated[str, Field(min_length=1)]
    """3-5 sentence executive summary of the compliance posture."""
