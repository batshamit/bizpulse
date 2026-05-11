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
    """The 4 L's — does this strategy actually serve the under-served?

    Customer-perspective inclusivity scoreboard (NOT the regulator's view).
    Each axis measures how well the recommendations include the typically-
    overlooked end of the customer spectrum. All values in [0, 1] where
    1 = strategy genuinely serves this segment; 0 = strategy ignores them.
    """

    last: float = Field(ge=0.0, le=1.0)
    """Last — the LAST customer in line. Late adopters, newcomers without
    history, waitlist / non-priority queues, low-engagement segments.
    1.0 = strategy has explicit onboarding / accessibility for first-timers
    and patient-customer flows."""

    least: float = Field(ge=0.0, le=1.0)
    """Least — the LEAST-considered audience. Minorities, regional /
    linguistic / accessibility / disability / senior-citizen / women-led
    SMB / rural / tier-3+ segments. 1.0 = explicit channels / creative /
    pricing for these audiences; 0 = generic mass-market only."""

    lost: float = Field(ge=0.0, le=1.0)
    """Lost — LOST or churned customers. Win-back, cart-abandoners, dormant
    accounts, prior cancellations. 1.0 = strategy has a named win-back
    motion with specific creative / incentive / channel; 0 = no recovery
    play."""

    lowest: float = Field(ge=0.0, le=1.0)
    """Lowest — the LOWEST-budget tier. Price-sensitive, financial-inclusion,
    first-job earners, students, micro-MSMEs, beneficiaries of subsidies.
    1.0 = entry tier / freemium / EMI / instalment offerings are part of
    the strategy; 0 = only premium / high-LTV segments served."""

    narrative: Annotated[str, Field(min_length=1)]
    """1-3 sentences explaining how the strategy serves (or misses) the
    under-served customers along each axis."""

    @property
    def average(self) -> float:
        return (self.last + self.least + self.lost + self.lowest) / 4.0


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
