"""Final marketing-strategy schema — the JSON the Strategist produces.

Mirrors the structure shown in section 2.4 of the project plan. Every
analytical field has a `citations` list; the Critic agent rejects any
analytical statement whose citations don't trace back to real chunks.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from bizpulse.models.agents import AgentTrace
from bizpulse.models.citations import Citation, _coerce_chunk_id
from bizpulse.models.common import BusinessId, ChunkId, StrictModel, TenantId
from bizpulse.models.compliance import ComplianceReport

ChannelSlug = Literal[
    "google_search",
    "linkedin",
    "youtube",
    "twitter",
    "instagram",
    "facebook",
    "podcast",
    "tv",
    "trade_publications",
    "trade_fairs",
    "whatsapp",
    "whatsapp_b2b",
    "newspaper_print",
    "email",
]

Priority = Literal["P0", "P1", "P2"]


# --- per-section analyses -----------------------------------------------------

class BrandAnalysis(StrictModel):
    positioning: str = Field(min_length=1)
    tone: str = Field(min_length=1)
    value_props: list[str] = Field(min_length=1)
    citations: list[Citation] = Field(min_length=1)


class AudiencePersona(StrictModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    motivations: list[str] = Field(default_factory=list)
    pain_points: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(min_length=1)


class AudienceAnalysis(StrictModel):
    primary: AudiencePersona
    secondary: list[AudiencePersona] = Field(default_factory=list)
    citations: list[Citation] = Field(min_length=1)


class Competitor(StrictModel):
    name: str = Field(min_length=1)
    url: str = Field(min_length=4)
    positioning: str = Field(min_length=1)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    verified: bool = Field(
        default=False,
        description="Competitor Scout MUST verify each competitor exists via independent web search before this is True.",
    )
    citations: list[Citation] = Field(min_length=1)


class CompetitiveLandscape(StrictModel):
    competitors: list[Competitor] = Field(min_length=1)
    market_position: str = Field(min_length=1)
    citations: list[Citation] = Field(min_length=1)


class ContentAuditFinding(StrictModel):
    observation: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    suggested_fix: str = Field(min_length=1)
    citations: list[Citation] = Field(min_length=1)


class ContentAudit(StrictModel):
    findings: list[ContentAuditFinding] = Field(default_factory=list)
    pillars_strong: list[str] = Field(default_factory=list)
    pillars_weak: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)


# --- recommendations ----------------------------------------------------------

class Recommendation(StrictModel):
    """One actionable marketing recommendation. Must cite chunk IDs."""

    channel: ChannelSlug
    action: str = Field(min_length=1, description="What to do, in one sentence.")
    rationale: str = Field(min_length=1, description="Why this works for this business.")
    evidence_chunk_ids: list[ChunkId] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    priority: Priority = "P1"
    expected_impact: str | None = Field(
        default=None,
        description="Optional one-liner on the metric this should move (e.g., 'CPL ↓ 15-25%').",
    )
    compliance_flags: list[str] = Field(
        default_factory=list,
        description="RBI/SEBI/RERA/etc. flags that the Critic should re-check.",
    )

    @field_validator("evidence_chunk_ids", mode="before")
    @classmethod
    def _lenient_evidence_ids(cls, v: object) -> list:
        """Coerce each evidence chunk_id leniently — same logic as Citation.
        Truncated / hallucinated IDs map to the UNKNOWN sentinel; the Critic
        agent flags them. Empty list after coercion is still rejected by
        min_length=1 below."""
        if not isinstance(v, list):
            return v
        return [_coerce_chunk_id(item) for item in v]

    @field_validator("evidence_chunk_ids")
    @classmethod
    def _evidence_non_empty(cls, v: list[ChunkId]) -> list[ChunkId]:
        # Belt-and-suspenders: Field(min_length=1) catches this, but the
        # Critic also explicitly checks here so the error message points
        # to *this* model when an LLM produces an unsupported recommendation.
        if not v:
            raise ValueError("Recommendation rejected: no evidence_chunk_ids cited.")
        return v


# --- final strategy -----------------------------------------------------------

class MarketingStrategy(StrictModel):
    """The end-to-end output of one BizPulse run — what gets returned to the
    caller, persisted in Postgres, and exposed via the MCP server.

    The four analytical fields (`brand`, `audience`, `competitive_landscape`,
    `content_audit`) are Optional because the strategist agent itself only
    needs to emit the synthesis-specific fields (recommendations, summary,
    overall_confidence). The orchestrator merges in the prior analyst
    outputs from state after the strategist returns. The full populated
    MarketingStrategy is what gets persisted and shown in the GUI; an
    incomplete one is fine for a partial / failed pipeline."""

    tenant_id: TenantId
    business_id: BusinessId
    industry: str
    brand: BrandAnalysis | None = None
    audience: AudienceAnalysis | None = None
    competitive_landscape: CompetitiveLandscape | None = None
    content_audit: ContentAudit | None = None
    recommendations: list[Recommendation] = Field(min_length=1)
    overall_confidence: float = Field(ge=0.0, le=1.0)
    summary: str = Field(min_length=1, description="3-5 sentence executive summary.")
    compliance_report: ComplianceReport | None = Field(
        default=None,
        description="Attached by the compliance_checker agent after synthesis. None when compliance was skipped.",
    )
    agent_traces: list[AgentTrace] = Field(
        default_factory=list,
        description="Per-node trace from the LangGraph run — agent name, status, duration, retry count, error if any.",
    )

    @field_validator("recommendations")
    @classmethod
    def _at_least_one_high_priority(cls, v: list[Recommendation]) -> list[Recommendation]:
        if not any(r.priority == "P0" for r in v):
            # Soft guidance — if you have no P0, you probably haven't really
            # made a recommendation. Don't fail here, but a follow-up
            # critic check will flag it.
            pass
        return v
