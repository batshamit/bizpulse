"""Tests for the strategy schema — citation-grounding contracts."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from bizpulse.models import (
    AudienceAnalysis,
    AudiencePersona,
    BrandAnalysis,
    Citation,
    CompetitiveLandscape,
    Competitor,
    ContentAudit,
    MarketingStrategy,
    Recommendation,
)


def _cite() -> Citation:
    return Citation(chunk_id=uuid4(), quote="evidence quote", confidence=0.9)


def test_recommendation_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        Recommendation(
            channel="linkedin",
            action="Post a thought-leadership piece",
            rationale="Audience is on LinkedIn",
            evidence_chunk_ids=[],  # empty -> reject
            confidence=0.8,
        )


def test_recommendation_minimal_valid() -> None:
    r = Recommendation(
        channel="linkedin",
        action="Post weekly architect-spec case studies",
        rationale="Buyer persona is technical and lives on LinkedIn",
        evidence_chunk_ids=[uuid4()],
        confidence=0.85,
    )
    assert r.priority == "P1"
    assert r.expected_impact is None


def test_marketing_strategy_round_trip_json() -> None:
    tenant_id = uuid4()
    business_id = uuid4()
    chunk_id = uuid4()

    strategy = MarketingStrategy(
        tenant_id=tenant_id,
        business_id=business_id,
        industry="fintech",
        brand=BrandAnalysis(
            positioning="Compliance-first neobank for salaried gig workers",
            tone="trustworthy, transparent",
            value_props=["full-KYC accounts", "instant credit-line"],
            citations=[_cite()],
        ),
        audience=AudienceAnalysis(
            primary=AudiencePersona(
                name="Gig-economy salaried",
                description="25-35yo metro tier-1 freelancers and platform workers",
                motivations=["smooth onboarding"],
                pain_points=["traditional bank rejection"],
                citations=[_cite()],
            ),
            citations=[_cite()],
        ),
        competitive_landscape=CompetitiveLandscape(
            competitors=[
                Competitor(
                    name="Jupiter",
                    url="https://jupiter.money",
                    positioning="Lifestyle-focused neobank",
                    verified=True,
                    citations=[_cite()],
                )
            ],
            market_position="Late entrant; differentiates on RBI compliance posture",
            citations=[_cite()],
        ),
        content_audit=ContentAudit(),
        recommendations=[
            Recommendation(
                channel="linkedin",
                action="Publish weekly RBI-compliance explainers",
                rationale="Audience is regulation-anxious",
                evidence_chunk_ids=[chunk_id],
                confidence=0.9,
                priority="P0",
            )
        ],
        overall_confidence=0.82,
        summary="Compliance-first positioning; lean into LinkedIn educational content.",
    )

    blob = strategy.model_dump_json()
    parsed = MarketingStrategy.model_validate_json(blob)
    assert parsed.tenant_id == tenant_id
    assert parsed.recommendations[0].evidence_chunk_ids[0] == chunk_id
