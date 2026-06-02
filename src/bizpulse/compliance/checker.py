"""Compliance checker — reviews a MarketingStrategy against applicable policies.

Runs as a dedicated step after the strategist. Uses the Council the same way
other agents do, but the prompt is custom because:
  - context is the structured strategy + the policy registry (not chunks)
  - output is ComplianceReport (not a per-agent analytical type)

Pattern: call council.debate() directly (bypassing AgentRunner) so we can
hand-build the prompt with both the strategy and the applicable policies.
JSON-repair fallback mirrors AgentRunner.
"""

from __future__ import annotations

import json
import time
from textwrap import dedent

from pydantic import ValidationError

from bizpulse.agents.council import Council
from bizpulse.agents.runner import AgentRunError, _compact_schema, extract_json
from bizpulse.compliance.policies import applicable
from bizpulse.logging import get_logger
from bizpulse.models.compliance import ComplianceReport, PolicyRef
from bizpulse.models.strategy import MarketingStrategy

log = get_logger(__name__)


_SYSTEM = dedent("""
    You are a dual-capability expert: an Elite Strategy Consultant and a Big-4 Regulatory Auditor (akin to Deloitte or PwC).
    Your objective is to review a MarketingStrategy against applicable policies and produce ONE JSON object matching the ComplianceReport schema.

    Your responsibilities are structured as follows:

    A. REGULATORY & POLICY ALIGNMENT (SECTION 4: BIG-4 GRADE STATUTORY & COMPLIANCE AUDIT - The Shield)
       Adopt the strict, unembellished, and rigorous tone of a top-tier audit firm (e.g., PwC, EY). Evaluate the marketing strategies proposed in the MarketingStrategy brief against severe legal and regulatory frameworks.
       Present this as a formal Risk Matrix.
       
       DETAILED FLAGS: For every Recommendation, evaluate alignment with ALL supplied company and government policies. If a recommendation triggers a policy's prohibitions or misses a required disclosure, add ONE ComplianceFlag. 
       
       For each ComplianceFlag:
         * Use Strict Risk Taxonomies: You MUST categorize findings strictly using severity levels (critical, violation, warning, advisory, info) which are rendered as [CRITICAL EXPOSURE], [HIGH RISK], or [OPERADVISORY].
         * Cite Frameworks: In the 'issue' field, you MUST reference specific regulatory bodies and legal frameworks relevant to the data/policies (e.g., MahaRERA disclosures, DPDP Act 2023 data consent, ASCI influencer guidelines, FEMA restrictions, SEC filings). Provide a detailed, clear explanation of how and why the recommendation conflicts with the rules.
         * Remediation: In the 'fix' field, you MUST provide a concrete, legally sound "Required Fix Action" (e.g., "Mandate Section 4(1) MahaRERA disclaimers on all YouTube walkthrough descriptions", "Provide clear opt-out consent mechanisms in line with DPDP Act 2023 before tracking user behavior").

       SCORING CLARITY: You MUST clarify the exact basis for your overall_compliance_score. If you give a 100% (1.0) score, justify why it is perfectly aligned with ALL policies. If lower, identify the specific violations or advisory gaps.

    B. THE 4 L's — CUSTOMER-INCLUSIVITY SCORECARD. Score each in [0, 1]:
         * last   — LAST customer in line: Late adopters, legacy/hesitant demographics. Strategy to convert legacy/hesitant demographics.
         * least  — LEAST-considered: Under-served segments, neglected market segments, or emerging micromarkets.
         * lost   — LOST/churned: Re-engagement tactics for lapsed clients/investors.
         * lowest — LOWEST-budget: Entry-tier offerings or top-of-funnel conversion tactics.

       narrative: 1-3 sentences explaining how the strategy serves (or misses) the under-served customer segments along the 4L Framework.

    C. OVERALL REPORT SUMMARY:
       The 'summary' field MUST be formatted as a highly professional, structured report with explicit uppercase markdown headers:
         ### EXECUTIVE SUMMARY
         [A high-level rollup of the strategy's overall compliance posture]
         
         ### KEY COMPLIANCE RISKS & EXPOSURES
         [Bullet points of any regulatory concerns, potential penalties, or severe exposure areas]
         
         ### STRATEGIC RECOMMENDATIONS FOR ALIGNMENT
         [Actionable strategic changes required to align the marketing campaign with policies and boost inclusivity]

       Make the summary comprehensive, rigorous, unembellished, and directly suitable for C-level executives.

    Reply ONLY with valid JSON matching ComplianceReport. No prose.
    """).strip()


def _format_policies(policies: list[PolicyRef]) -> str:
    lines = []
    for p in policies:
        loc = f"{p.country}" + (f"/{p.state}" if p.state else "")
        lines.append(
            f"- [{p.slug}] {p.body} — {p.title} ({loc}, severity={p.severity}, updated={p.last_updated})\n"
            f"  summary: {p.summary}"
        )
        if p.prohibitions:
            lines.append("  prohibits: " + "; ".join(p.prohibitions))
        if p.required_disclosures:
            lines.append("  requires_disclosure: " + "; ".join(p.required_disclosures))
        if p.indicative_penalty:
            lines.append("  penalty: " + p.indicative_penalty)
    return "\n".join(lines)


def _strategy_brief(strategy: MarketingStrategy) -> str:
    """Compact JSON view of the strategy that fits in a small prompt budget.

    Drops the verbose nested analytical objects (brand/audience/competitive_/
    content_) — the compliance checker only really needs to score the
    recommendations + summary against policies. If a recommendation cites
    an analyst-output claim, the chunk_ids on the recommendation itself
    are enough for traceability."""
    competitor_names = []
    if strategy.competitive_landscape:
        competitor_names = [c.name for c in strategy.competitive_landscape.competitors[:6]]

    brief: dict[str, object] = {
        "industry": strategy.industry,
        "summary": strategy.summary,
        "competitor_names": competitor_names,
        "recommendations": [
            {
                "channel": r.channel,
                "action": r.action,
                "rationale": r.rationale[:300],
                "priority": r.priority,
                "confidence": r.confidence,
                "compliance_flags": r.compliance_flags,
                "evidence_chunk_ids": [str(cid)[:8] for cid in r.evidence_chunk_ids[:3]],
            }
            for r in strategy.recommendations
        ],
    }
    return json.dumps(brief, indent=2)


def _build_user_prompt(
    *,
    strategy: MarketingStrategy,
    policies: list[PolicyRef],
    country: str,
    state: str | None,
    schema_json: str,
) -> str:
    return (
        f"Country: {country}" + (f", State: {state}" if state else "") + "\n"
        f"Industry: {strategy.industry}\n\n"
        "----- APPLICABLE POLICIES -----\n"
        f"{_format_policies(policies)}\n"
        "----- END POLICIES -----\n\n"
        "----- STRATEGY UNDER REVIEW (brief) -----\n"
        f"{_strategy_brief(strategy)}\n"
        "----- END STRATEGY -----\n\n"
        f"Reply with ONLY a JSON object matching this exact ComplianceReport schema:\n"
        f"```json\n{schema_json}\n```\n\n"
        "Set policies_considered to the slugs you actually evaluated."
    )


async def run_compliance_check(
    *,
    council: Council,
    strategy: MarketingStrategy,
    country: str = "IN",
    state: str | None = None,
) -> ComplianceReport:
    """Run the compliance checker against a strategy. Returns a ComplianceReport.

    Raises AgentRunError if the council can't produce a schema-valid report
    after one repair attempt — the caller decides whether to use a stub
    report or block the analysis.
    """
    t0 = time.perf_counter()
    policies = applicable(industry=strategy.industry, country=country, state=state)
    log.info(
        "compliance.start",
        industry=strategy.industry,
        country=country,
        state=state,
        n_policies=len(policies),
    )

    schema_json = json.dumps(_compact_schema(ComplianceReport), indent=2)
    user = _build_user_prompt(
        strategy=strategy,
        policies=policies,
        country=country,
        state=state,
        schema_json=schema_json,
    )
    council_result = await council.debate(system=_SYSTEM, user=user)
    # Surface usage to callers via the council_result return path:
    # callers (runner_service) read council_result.cost_usd directly.

    repair = False
    try:
        data = extract_json(council_result.final)
        report = ComplianceReport.model_validate(data)
    except (ValueError, ValidationError) as first_err:
        log.warning(
            "compliance.parse_failed_attempting_repair",
            error=str(first_err)[:300],
        )
        repair = True
        repair_user = (
            f"Your previous response did not pass schema validation against "
            f"ComplianceReport. The error was:\n\n{first_err}\n\n"
            f"Schema:\n```json\n{schema_json}\n```\n\n"
            f"Your previous text:\n\n{council_result.final}\n\n"
            "Reply with ONLY a corrected JSON object that matches exactly. "
            "No prose, no fences."
        )
        try:
            cr = await council.judge.complete(
                system=_SYSTEM,
                user=repair_user,
                max_tokens=council.max_tokens,
                temperature=0.0,
            )
            data = extract_json(cr.text)
            report = ComplianceReport.model_validate(data)
        except (ValueError, ValidationError) as second_err:
            raise AgentRunError(
                "compliance_checker failed to produce a ComplianceReport "
                "after one repair attempt",
                raw_text=council_result.final,
                validation_error=str(second_err),
            ) from second_err

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    log.info(
        "compliance.complete",
        n_flags=len(report.flags),
        overall=report.overall_compliance_score,
        repaired=repair,
        latency_ms=elapsed_ms,
        cost_usd=council_result.cost_usd,
    )
    return report
