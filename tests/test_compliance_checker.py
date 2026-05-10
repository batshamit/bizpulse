"""Tests for the compliance_checker — runs against a fake Council that
returns a hand-built ComplianceReport JSON."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from bizpulse.agents.council import Council
from bizpulse.compliance.checker import run_compliance_check
from bizpulse.compliance.policies import applicable
from bizpulse.llm import FakeLLMClient
from bizpulse.models import (
    AudienceAnalysis,
    AudiencePersona,
    BrandAnalysis,
    Citation,
    Competitor,
    CompetitiveLandscape,
    ContentAudit,
    MarketingStrategy,
    Recommendation,
)
from bizpulse.models.compliance import ComplianceReport


def _strategy() -> MarketingStrategy:
    cid = uuid4()
    return MarketingStrategy(
        tenant_id=uuid4(), business_id=uuid4(), industry="real_estate",
        brand=BrandAnalysis(
            positioning="Luxury residential builder", tone="trustworthy",
            value_props=["assured possession", "RERA-compliant"],
            citations=[Citation(chunk_id=cid)],
        ),
        audience=AudienceAnalysis(
            primary=AudiencePersona(
                name="Upgrader", description="35-50yo metro family",
                citations=[Citation(chunk_id=cid)],
            ),
            citations=[Citation(chunk_id=cid)],
        ),
        competitive_landscape=CompetitiveLandscape(
            competitors=[Competitor(
                name="Lodha", url="https://lodhagroup.in",
                positioning="luxury", verified=True,
                citations=[Citation(chunk_id=cid)],
            )],
            market_position="late entrant",
            citations=[Citation(chunk_id=cid)],
        ),
        content_audit=ContentAudit(),
        recommendations=[Recommendation(
            channel="instagram", action="Post 'guaranteed possession in 18 months' Reels",
            rationale="Hooks the upgrade buyer", evidence_chunk_ids=[cid],
            confidence=0.85, priority="P0",
        )],
        overall_confidence=0.82,
        summary="Lean into Reels.",
    )


def _canned_report_for_maharashtra() -> dict:
    """A plausible compliance report — flags the 'guaranteed possession'
    Recommendation under MahaRERA + ASCI."""
    return {
        "country": "IN",
        "state": "maharashtra",
        "policies_considered": ["rera-maharashtra", "asci-code", "dpdp-act-2023"],
        "flags": [
            {
                "policy_slug": "rera-maharashtra",
                "severity": "violation",
                "issue": "Recommendation promises 'guaranteed possession in 18 months' without referencing MahaRERA registration; promised possession dates outside the RERA filing are violations.",
                "fix": "Replace with 'targeted possession per MahaRERA filing P5170...'; include MahaRERA registration on every creative.",
                "evidence_chunk_ids": [],
            },
            {
                "policy_slug": "asci-code",
                "severity": "warning",
                "issue": "Influencer creative would need #ad / #partnership disclosure if any endorser is involved.",
                "fix": "Mandate disclosure on creator briefs.",
                "evidence_chunk_ids": [],
            },
        ],
        "competitor_compare": [
            {
                "competitor_name": "Lodha",
                "relative_posture": "weaker",
                "rationale": "Lodha quotes RERA on every creative; this strategy does not.",
                "evidence_chunk_ids": [],
            },
        ],
        "metrics": {
            "latest": 0.95,
            "least": 0.35,
            "lost": 0.55,
            "lowest": 0.7,
            "narrative": "One MahaRERA violation drags Least sharply; recent-regulation coverage is strong.",
        },
        "overall_compliance_score": 0.45,
        "summary": "Strategy hits a critical MahaRERA disclosure gap and an ASCI influencer-disclosure warning. Fix RERA citation first.",
    }


@pytest.mark.asyncio
async def test_run_compliance_check_happy_path() -> None:
    canned = json.dumps(_canned_report_for_maharashtra())
    judge = FakeLLMClient(name="judge", vendor="fake", response=canned)
    member = FakeLLMClient(name="m", vendor="fake", response=canned)
    council = Council(members=[member], judge=judge, rounds=1, max_tokens=2048)

    report = await run_compliance_check(
        council=council,
        strategy=_strategy(),
        country="IN",
        state="maharashtra",
    )

    assert isinstance(report, ComplianceReport)
    assert report.country == "IN"
    assert report.state == "maharashtra"
    assert any(f.policy_slug == "rera-maharashtra" and f.severity == "violation" for f in report.flags)
    assert report.metrics.average == pytest.approx((0.95 + 0.35 + 0.55 + 0.7) / 4)
    assert report.overall_compliance_score == 0.45
    assert any(c.competitor_name == "Lodha" for c in report.competitor_compare)


@pytest.mark.asyncio
async def test_applicable_filter_picks_state_specific_policies() -> None:
    """Sanity check that the registry actually returns the right policies
    for real_estate + IN + maharashtra (so the prompt is built correctly)."""
    pols = applicable(industry="real_estate", country="IN", state="maharashtra")
    slugs = {p.slug for p in pols}
    assert "rera-maharashtra" in slugs
    assert "rera-karnataka" not in slugs
    assert "dpdp-act-2023" in slugs
    assert "asci-code" in slugs
