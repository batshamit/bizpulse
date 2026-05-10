"""Tests for the compliance models + policy registry."""

from __future__ import annotations

import pytest

from bizpulse.compliance import (
    POLICIES,
    applicable,
    list_policies,
    supported_countries,
    supported_states,
)
from bizpulse.models.compliance import (
    ComplianceFlag,
    ComplianceReport,
    LLLLMetric,
    PolicyRef,
)


# ---- registry --------------------------------------------------------------

def test_registry_has_minimum_coverage() -> None:
    assert len(list_policies()) >= 25, "registry should have at least 25 policies"


def test_supported_countries() -> None:
    countries = supported_countries()
    assert {"IN", "EU", "US", "GB"} <= countries


def test_supported_states_for_india() -> None:
    states = supported_states("IN")
    # at least 3 RERA states
    assert {"maharashtra", "karnataka", "tamil_nadu"} <= states


def test_applicable_filter_by_country() -> None:
    eu = applicable(industry="fintech", country="EU")
    assert all(p.country == "EU" for p in eu)
    assert any(p.slug == "eu-gdpr" for p in eu)
    assert all(p.slug != "rbi-digital-lending-2022" for p in eu)


def test_applicable_filter_by_industry() -> None:
    fintech_in = applicable(industry="fintech", country="IN")
    real_estate_in = applicable(industry="real_estate", country="IN")

    fintech_slugs = {p.slug for p in fintech_in}
    re_slugs = {p.slug for p in real_estate_in}

    # Industry-specific
    assert "rbi-digital-lending-2022" in fintech_slugs
    assert "rbi-digital-lending-2022" not in re_slugs
    assert "rera-maharashtra" not in fintech_slugs

    # Cross-industry
    for shared in ("dpdp-act-2023", "cpa-misleading-ads-2019", "asci-code"):
        assert shared in fintech_slugs
        assert shared in re_slugs


def test_state_specific_only_when_requested() -> None:
    """Without a state, RERA-Maharashtra should NOT be returned for real_estate;
    with state='maharashtra', it should."""
    nat = applicable(industry="real_estate", country="IN", state=None)
    nat_slugs = {p.slug for p in nat}
    assert "rera-maharashtra" not in nat_slugs
    assert "dpdp-act-2023" in nat_slugs

    mh = applicable(industry="real_estate", country="IN", state="maharashtra")
    mh_slugs = {p.slug for p in mh}
    assert "rera-maharashtra" in mh_slugs
    assert "rera-karnataka" not in mh_slugs


def test_every_policy_has_required_fields() -> None:
    for p in POLICIES.values():
        assert p.slug and p.body and p.title and p.summary
        assert p.country in {"IN", "EU", "US", "GB"}
        assert p.severity in {"info", "advisory", "warning", "violation", "critical"}


# ---- model construction ----------------------------------------------------

def test_llll_metric_average_and_validation() -> None:
    m = LLLLMetric(
        latest=0.9, least=0.7, lost=0.8, lowest=0.85,
        narrative="Strong recent-regulation coverage; one warning-tier flag.",
    )
    assert m.average == pytest.approx((0.9 + 0.7 + 0.8 + 0.85) / 4)


def test_llll_metric_rejects_out_of_range() -> None:
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        LLLLMetric(latest=1.5, least=0.5, lost=0.5, lowest=0.5, narrative="x")


def test_compliance_flag_minimal() -> None:
    f = ComplianceFlag(
        policy_slug="rbi-digital-lending-2022",
        severity="violation",
        issue="Recommendation uses 'guaranteed approval' language.",
        fix="Replace with 'subject to credit policy'.",
    )
    assert f.policy_slug in POLICIES


def test_compliance_report_round_trip() -> None:
    rpt = ComplianceReport(
        country="IN",
        state="maharashtra",
        policies_considered=["rera-maharashtra", "dpdp-act-2023"],
        flags=[
            ComplianceFlag(
                policy_slug="rera-maharashtra",
                severity="violation",
                issue="Project ad lacks MahaRERA registration number.",
                fix="Append 'MahaRERA: P5170...' to all promotional creatives.",
            ),
        ],
        metrics=LLLLMetric(
            latest=0.95, least=0.6, lost=0.7, lowest=0.8,
            narrative="One MahaRERA disclosure gap; otherwise strong DPDP posture.",
        ),
        overall_compliance_score=0.72,
        summary="One critical RERA disclosure missing; DPDP and ASCI disclosures in good shape.",
    )
    blob = rpt.model_dump_json()
    rpt2 = ComplianceReport.model_validate_json(blob)
    assert rpt2.flags[0].policy_slug == "rera-maharashtra"
    assert rpt2.metrics.average == pytest.approx((0.95 + 0.6 + 0.7 + 0.8) / 4)
