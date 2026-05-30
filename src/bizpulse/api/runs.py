"""Run record lookup + chat."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from fpdf import FPDF
from pydantic import BaseModel
from qdrant_client import QdrantClient

from bizpulse.agents.chatter import chat_about_recommendation
from bizpulse.agents.runner import AgentRunner
from bizpulse.api.dependencies import get_store, require_tenant
from bizpulse.api.runner_service import _pick_council, _pick_embedder
from bizpulse.models import RunRecord, Tenant
from bizpulse.retrieval.qdrant_repo import TenantQdrant
from bizpulse.retrieval.search import RetrievalEngine
from bizpulse.storage import Store

router = APIRouter(prefix="/v1/runs", tags=["runs"])

_QDRANT_BASE = Path(
    os.environ.get("BIZPULSE_QDRANT_DIR", str(Path(tempfile.gettempdir()) / "bizpulse-qdrant"))
)


@router.get("/{run_id}", response_model=RunRecord)
def get_run(
    run_id: UUID,
    tenant: Tenant = Depends(require_tenant),
    store: Store = Depends(get_store),
) -> RunRecord:
    run = store.get_run(run_id)
    if run is None or run.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return run


class BizPulsePDF(FPDF):
    def __init__(self, *args: Any, title: str = "BizPulse Marketing Strategy Report", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.report_title = title

    def header(self) -> None:
        self.set_font("helvetica", "B", 16)
        self.cell(
            0,
            10,
            self.report_title,
            border=0,
            new_x="LMARGIN",
            new_y="NEXT",
            align="L",
        )
        self.set_draw_color(204, 120, 92)  # bzp-accent
        self.line(10, 20, 200, 20)
        self.ln(10)

    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("helvetica", "I", 8)
        self.cell(0, 10, f"Page {self.page_no()} | Confidential Business Intelligence", align="C")


@router.get("/{run_id}/pdf")
def download_pdf(
    run_id: UUID,
    tenant: Tenant = Depends(require_tenant),
    store: Store = Depends(get_store),
) -> Response:
    run = store.get_run(run_id)
    if run is None or run.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    if run.final_output is None:
        raise HTTPException(status_code=400, detail="run has no final strategy to download")

    if run.run_type == "daily_research":
        from bizpulse.models import DailyResearchReport
        s = run.final_output
        assert isinstance(s, DailyResearchReport)

        pdf = BizPulsePDF(title="BizPulse Daily Research Report")
        pdf.add_page()

        # Metadata
        pdf.set_font("helvetica", "B", 10)
        pdf.cell(40, 7, "Business URL:")
        pdf.set_font("helvetica", "", 10)
        pdf.cell(0, 7, str(run.business_id), new_x="LMARGIN", new_y="NEXT")

        pdf.set_font("helvetica", "B", 10)
        pdf.cell(40, 7, "Industry:")
        pdf.set_font("helvetica", "", 10)
        pdf.cell(0, 7, s.industry, new_x="LMARGIN", new_y="NEXT")

        pdf.set_font("helvetica", "B", 10)
        pdf.cell(40, 7, "Date:")
        pdf.set_font("helvetica", "", 10)
        pdf.cell(0, 7, str(run.finished_at or run.started_at), new_x="LMARGIN", new_y="NEXT")

        pdf.set_font("helvetica", "B", 10)
        pdf.cell(40, 7, "Confidence Score:")
        pdf.set_font("helvetica", "", 10)
        pdf.cell(0, 7, f"{int(s.overall_confidence * 100)}%", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)

        # Most Important Update
        pdf.set_fill_color(245, 235, 230)  # light background accent
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(0, 8, "MOST CRITICAL UPDATE", new_x="LMARGIN", new_y="NEXT", fill=True)
        pdf.set_font("helvetica", "B", 10)
        pdf.multi_cell(0, 6, s.most_important_update)
        pdf.ln(8)

        # Academic & Technological Innovations
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(0, 8, "Academic & Technological Innovations", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("helvetica", "", 10)
        if s.academic_research:
            for paper in s.academic_research:
                pdf.multi_cell(0, 6, f"- {paper.title}\n  Key Findings: {paper.key_findings}\n  Application: {paper.business_application}")
                pdf.ln(1)
        else:
            pdf.set_font("helvetica", "I", 10)
            pdf.cell(0, 6, "No academic research reported.", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("helvetica", "", 10)
        pdf.ln(5)

        # Policy, Regulations & Budget Updates
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(0, 8, "Regulatory, Policy & Geopolitical Updates", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("helvetica", "", 10)
        pol = s.policy_and_politics
        has_pol = bool(pol.regulatory or pol.financial or pol.geopolitical)
        if has_pol:
            if pol.regulatory:
                for item in pol.regulatory:
                    pdf.multi_cell(0, 6, f"- Regulatory: {item}")
                    pdf.ln(1)
            if pol.financial:
                for item in pol.financial:
                    pdf.multi_cell(0, 6, f"- Financial/Budget: {item}")
                    pdf.ln(1)
            if pol.geopolitical:
                for item in pol.geopolitical:
                    pdf.multi_cell(0, 6, f"- Geopolitical/Trade: {item}")
                    pdf.ln(1)
        else:
            pdf.set_font("helvetica", "I", 10)
            pdf.cell(0, 6, "No policy or regulatory updates reported.", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("helvetica", "", 10)
        pdf.ln(5)

        # Strategic Business Deals & Investments
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(0, 8, "Strategic Corporate Deals & Partnerships", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("helvetica", "", 10)
        if s.business_deals:
            for deal in s.business_deals:
                pdf.multi_cell(0, 6, f"- {deal.entities}\n  Strategic Impact: {deal.strategic_impact}")
                pdf.ln(1)
        else:
            pdf.set_font("helvetica", "I", 10)
            pdf.cell(0, 6, "No strategic business deals reported.", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("helvetica", "", 10)
        pdf.ln(5)

        # Environmental & Climate Matrix
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(0, 8, "Environmental & Climate Risk Matrix", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("helvetica", "", 10)
        cli = s.climate_and_weather
        has_cli = bool(cli.threats or cli.opportunities)
        if has_cli:
            if cli.threats:
                for t in cli.threats:
                    pdf.multi_cell(0, 6, f"- Threat: {t}")
                    pdf.ln(1)
            if cli.opportunities:
                for o in cli.opportunities:
                    pdf.multi_cell(0, 6, f"- Opportunity: {o}")
                    pdf.ln(1)
        else:
            pdf.set_font("helvetica", "I", 10)
            pdf.cell(0, 6, "No environmental or climate updates reported.", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("helvetica", "", 10)
        pdf.ln(5)

        # Competitor Intelligence & Sentiment
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(0, 8, "Competitor Intelligence & Sentiment", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("helvetica", "", 10)
        comp = s.competitors_and_products
        has_comp = bool(comp.new_products or comp.competitor_moves or comp.client_sentiment)
        if has_comp:
            if comp.new_products:
                for np in comp.new_products:
                    pdf.multi_cell(0, 6, f"- New Product: {np}")
                    pdf.ln(1)
            if comp.competitor_moves:
                for m in comp.competitor_moves:
                    pdf.multi_cell(0, 6, f"- Competitor Move: {m}")
                    pdf.ln(1)
            if comp.client_sentiment:
                for cs in comp.client_sentiment:
                    pdf.multi_cell(0, 6, f"- Client Sentiment/Demand: {cs}")
                    pdf.ln(1)
        else:
            pdf.set_font("helvetica", "I", 10)
            pdf.cell(0, 6, "No competitor updates reported.", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("helvetica", "", 10)
        pdf.ln(5)

        # Emerging Radar Anomaly Signals
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(0, 8, "Emerging Radar Anomaly Signals", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("helvetica", "", 10)
        if s.emerging_radar:
            for item in s.emerging_radar:
                pdf.multi_cell(0, 6, f"- {item}")
                pdf.ln(1)
        else:
            pdf.set_font("helvetica", "I", 10)
            pdf.cell(0, 6, "No emerging radar anomalies detected.", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("helvetica", "", 10)
        pdf.ln(5)

        # Uncertainty Log
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(0, 8, "Groundedness & Uncertainty Audit", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("helvetica", "", 10)
        if s.uncertainty_log:
            for item in s.uncertainty_log:
                pdf.multi_cell(0, 6, f"- {item}")
                pdf.ln(1)
        else:
            pdf.set_font("helvetica", "I", 10)
            pdf.cell(0, 6, "All reported facts fully grounded and verified.", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("helvetica", "", 10)
        pdf.ln(5)

        # Citations
        if s.citations:
            pdf.set_font("helvetica", "B", 12)
            pdf.cell(0, 8, "Sources & Citations", new_x="LMARGIN", new_y="NEXT")
            for idx, cit in enumerate(s.citations, 1):
                pdf.set_font("helvetica", "B", 9)
                pdf.cell(0, 5, f"Source #{idx} (Confidence: {int(cit.confidence * 100)}%)", new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("helvetica", "", 9)
                txt = f"Chunk ID: {cit.chunk_id}"
                if cit.quote:
                    txt = f"Quote: \"{cit.quote}\"\n{txt}"
                pdf.multi_cell(0, 5, txt)
                pdf.ln(2)

        content = bytes(pdf.output())
        filename = f"BizPulse_Report_{run_id}.pdf"
        return Response(
            content=content,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    from bizpulse.models import MarketingStrategy
    s = run.final_output
    assert isinstance(s, MarketingStrategy)
    pdf = BizPulsePDF()
    pdf.add_page()

    # Metadata
    pdf.set_font("helvetica", "B", 10)
    pdf.cell(40, 7, "Business URL:")
    pdf.set_font("helvetica", "", 10)
    pdf.cell(0, 7, str(run.business_id), new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("helvetica", "B", 10)
    pdf.cell(40, 7, "Industry:")
    pdf.set_font("helvetica", "", 10)
    pdf.cell(0, 7, s.industry, new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("helvetica", "B", 10)
    pdf.cell(40, 7, "Date:")
    pdf.set_font("helvetica", "", 10)
    pdf.cell(0, 7, str(run.finished_at or run.started_at), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # Executive Summary
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 10, "Executive Summary", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "", 10)
    pdf.multi_cell(0, 6, s.summary)
    pdf.ln(5)

    # 4 L's
    if s.inclusivity_metrics:
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(0, 10, "Inclusivity Scorecard (4 L's)", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("helvetica", "", 10)
        m = s.inclusivity_metrics
        pdf.cell(
            0,
            6,
            f"LAST (Late Adopters): {int(m.last*100)}% | LEAST (Under-served): {int(m.least*100)}%",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.cell(
            0,
            6,
            f"LOST (Churned): {int(m.lost*100)}% | LOWEST (Budget): {int(m.lowest*100)}%",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.ln(2)
        pdf.set_font("helvetica", "I", 9)
        pdf.multi_cell(0, 5, m.narrative)
        pdf.ln(5)

    # Recommendations
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 10, "Recommendations", new_x="LMARGIN", new_y="NEXT")
    for r in s.recommendations:
        pdf.set_font("helvetica", "B", 10)
        pdf.cell(0, 7, f"{r.priority}: {r.action} ({r.channel})", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("helvetica", "", 10)
        pdf.multi_cell(0, 6, f"Rationale: {r.rationale}")
        pdf.ln(2)

    # Detailed Channels
    if s.detailed_channel_strategies:
        pdf.add_page()
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(0, 10, "Detailed Channel Strategies", new_x="LMARGIN", new_y="NEXT")
        for ds in s.detailed_channel_strategies:
            pdf.set_font("helvetica", "B", 11)
            pdf.cell(0, 8, ds.channel.upper().replace("_", " "), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("helvetica", "", 10)
            pdf.multi_cell(0, 6, ds.strategy_details)
            pdf.ln(2)
            if ds.key_metrics:
                pdf.set_font("helvetica", "I", 9)
                pdf.cell(
                    0, 6, "Key Metrics: " + ", ".join(ds.key_metrics), new_x="LMARGIN", new_y="NEXT"
                )
            pdf.ln(4)

    # Benefit Report
    if s.benefit_report:
        pdf.ln(5)
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(0, 10, "Business Benefit Report", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("helvetica", "", 10)
        pdf.multi_cell(0, 6, s.benefit_report)
        pdf.ln(2)

    # Compliance
    if s.compliance_report:
        pdf.add_page()
        cr = s.compliance_report
        pdf.set_font("helvetica", "B", 12)
        pdf.cell(
            0,
            10,
            f"Compliance Audit - Overall Score: {int(cr.overall_compliance_score*100)}%",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.set_font("helvetica", "", 10)
        pdf.multi_cell(0, 6, cr.summary)
        pdf.ln(4)
        pdf.set_font("helvetica", "B", 11)
        pdf.cell(0, 8, "Flags / Issues", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("helvetica", "", 10)
        for f in cr.flags:
            pdf.set_font("helvetica", "B", 9)
            pdf.cell(0, 5, f"[{f.severity.upper()}] {f.policy_slug}", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("helvetica", "", 9)
            pdf.multi_cell(0, 5, f.issue)
            pdf.ln(2)
            if f.fix:
                pdf.set_text_color(58, 130, 89)  # bzp-success
                pdf.multi_cell(0, 5, f"Fix: {f.fix}")
                pdf.set_text_color(0, 0, 0)
                pdf.ln(2)

    content = bytes(pdf.output())
    filename = f"BizPulse_Report_{run_id}.pdf"
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{run_id}/download")
def download_run(
    run_id: UUID,
    tenant: Tenant = Depends(require_tenant),
    store: Store = Depends(get_store),
) -> Response:
    run = store.get_run(run_id)
    if run is None or run.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    if run.final_output is None:
        raise HTTPException(status_code=400, detail="run has no final strategy to download")

    if run.run_type == "daily_research":
        from bizpulse.models import DailyResearchReport
        s = run.final_output
        assert isinstance(s, DailyResearchReport)

        md = [
            "# BizPulse Daily Research Report",
            f"**Business URL:** {run.business_id}",
            f"**Industry:** {s.industry}",
            f"**Date:** {run.finished_at or run.started_at}",
            f"**Confidence Score:** {int(s.overall_confidence * 100)}%",
            f"\n## Most Critical Update\n> {s.most_important_update}",
            "\n## Academic & Technological Innovations",
        ]
        if s.academic_research:
            for paper in s.academic_research:
                md.append(f"- **Title:** {paper.title}\n  *Key Findings:* {paper.key_findings}\n  *Application:* {paper.business_application}")
        else:
            md.append("*No academic research reported.*")

        md.append("\n## Regulatory, Policy & Geopolitical Updates")
        pol = s.policy_and_politics
        has_pol = bool(pol.regulatory or pol.financial or pol.geopolitical)
        if has_pol:
            if pol.regulatory:
                for item in pol.regulatory:
                    md.append(f"- **Regulatory:** {item}")
            if pol.financial:
                for item in pol.financial:
                    md.append(f"- **Financial/Budget:** {item}")
            if pol.geopolitical:
                for item in pol.geopolitical:
                    md.append(f"- **Geopolitical/Trade:** {item}")
        else:
            md.append("*No policy or regulation updates reported.*")

        md.append("\n## Strategic Corporate Deals & Partnerships")
        if s.business_deals:
            for deal in s.business_deals:
                md.append(f"- **Entities:** {deal.entities}\n  *Strategic Impact:* {deal.strategic_impact}")
        else:
            md.append("*No strategic business deals reported.*")

        md.append("\n## Environmental & Climate Risk Matrix")
        cli = s.climate_and_weather
        has_cli = bool(cli.threats or cli.opportunities)
        if has_cli:
            if cli.threats:
                for t in cli.threats:
                    md.append(f"- **Threat:** {t}")
            if cli.opportunities:
                for o in cli.opportunities:
                    md.append(f"- **Opportunity:** {o}")
        else:
            md.append("*No environmental or climate updates reported.*")

        md.append("\n## Competitor Intelligence & Sentiment")
        comp = s.competitors_and_products
        has_comp = bool(comp.new_products or comp.competitor_moves or comp.client_sentiment)
        if has_comp:
            if comp.new_products:
                for np in comp.new_products:
                    md.append(f"- **New Product:** {np}")
            if comp.competitor_moves:
                for m in comp.competitor_moves:
                    md.append(f"- **Competitor Move:** {m}")
            if comp.client_sentiment:
                for cs in comp.client_sentiment:
                    md.append(f"- **Client Sentiment/Demand:** {cs}")
        else:
            md.append("*No competitor updates reported.*")

        md.append("\n## Emerging Radar Anomaly Signals")
        if s.emerging_radar:
            for item in s.emerging_radar:
                md.append(f"- {item}")
        else:
            md.append("*No emerging radar anomalies detected.*")

        md.append("\n## Groundedness & Uncertainty Audit")
        if s.uncertainty_log:
            for item in s.uncertainty_log:
                md.append(f"- {item}")
        else:
            md.append("*All reported facts fully grounded and verified.*")

        if s.citations:
            md.append("\n## Sources & Citations")
            for idx, cit in enumerate(s.citations, 1):
                md.append(f"### Source #{idx}")
                md.append(f"- **Confidence:** {int(cit.confidence * 100)}%")
                if cit.quote:
                    md.append(f"- **Quote:** \"{cit.quote}\"")
                md.append(f"- **Chunk ID:** `{cit.chunk_id}`")

        content = "\n".join(md)
        filename = f"BizPulse_Report_{run_id}.md"
        return Response(
            content=content,
            media_type="text/markdown",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    from bizpulse.models import MarketingStrategy
    s = run.final_output
    assert isinstance(s, MarketingStrategy)
    md = [
        "# BizPulse Marketing Strategy Report",
        f"**Business URL:** {run.business_id}",
        f"**Industry:** {s.industry}",
        f"**Date:** {run.finished_at or run.started_at}",
        f"\n## Executive Summary\n{s.summary}",
        f"\n## Brand Positioning\n{s.brand.positioning if s.brand else 'N/A'}",
        "\n## Recommendations",
    ]
    for r in s.recommendations:
        md.append(f"### {r.priority}: {r.action} ({r.channel})")
        md.append(f"**Rationale:** {r.rationale}")
        if r.expected_impact:
            md.append(f"**Impact:** {r.expected_impact}")

    if s.detailed_channel_strategies:
        md.append("\n## Detailed Channel Strategies")
        for ds in s.detailed_channel_strategies:
            md.append(f"### {ds.channel}")
            md.append(ds.strategy_details)
            if ds.key_metrics:
                md.append("**Key Metrics:** " + ", ".join(ds.key_metrics))

    if s.inclusivity_metrics:
        m = s.inclusivity_metrics
        md.append("\n## Inclusivity Scorecard (4 L's)")
        md.append(f"- **LAST (Late Adopters):** {int(m.last*100)}%")
        md.append(f"- **LEAST (Under-served):** {int(m.least*100)}%")
        md.append(f"- **LOST (Churned):** {int(m.lost*100)}%")
        md.append(f"- **LOWEST (Budget):** {int(m.lowest*100)}%")
        md.append(f"\n**Narrative:** {m.narrative}")

    if s.benefit_report:
        md.append(f"\n## Business Benefit Report\n{s.benefit_report}")

    if s.compliance_report:
        cr = s.compliance_report
        md.append("\n## Compliance Audit")
        md.append(f"**Overall Score:** {int(cr.overall_compliance_score*100)}%")
        md.append("\n### Flags")
        for f in cr.flags:
            md.append(f"- **[{f.severity.upper()}] {f.policy_slug}:** {f.issue}")
            if f.fix:
                md.append(f"  *Fix:* {f.fix}")
        md.append(f"\n**Summary:** {cr.summary}")

    content = "\n".join(md)
    filename = f"BizPulse_Report_{run_id}.md"
    return Response(
        content=content,
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


class RecommendationChatRequest(BaseModel):
    recommendation_index: int
    message: str


class RecommendationChatResponse(BaseModel):
    reply: str


@router.post("/{run_id}/chat", response_model=RecommendationChatResponse)
async def chat_run(
    run_id: UUID,
    body: RecommendationChatRequest,
    tenant: Tenant = Depends(require_tenant),
    store: Store = Depends(get_store),
) -> RecommendationChatResponse:
    run = store.get_run(run_id)
    if run is None or run.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="run not found")
    if run.run_type == "daily_research":
        raise HTTPException(status_code=400, detail="Chat is only supported for marketing strategy reports")
    if run.final_output is None:
        raise HTTPException(status_code=400, detail="run has no final strategy to chat about")

    from bizpulse.models import MarketingStrategy
    s = run.final_output
    assert isinstance(s, MarketingStrategy)

    council = _pick_council()
    if council is None:
        raise HTTPException(status_code=503, detail="LLM services unavailable")

    # Build a minimal runner for context retrieval (if needed) and council access
    qd_dir = _QDRANT_BASE / f"run-{run_id}"
    repo = TenantQdrant(tenant.id, client=QdrantClient(path=str(qd_dir)))
    runner = AgentRunner(
        retrieval=RetrievalEngine(repo, embedder=_pick_embedder()),
        council=council,
        industry=s.industry,
    )

    reply = await chat_about_recommendation(
        runner=runner,
        strategy=s,
        recommendation_index=body.recommendation_index,
        user_message=body.message,
    )

    return RecommendationChatResponse(reply=reply)


@router.delete("/{run_id}", status_code=status.HTTP_200_OK)
def delete_run(
    run_id: UUID,
    tenant: Tenant = Depends(require_tenant),
    store: Store = Depends(get_store),
) -> dict:
    run = store.get_run(run_id)
    if run is None or run.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="run not found")
    success = store.delete_run(run_id)
    if not success:
        raise HTTPException(status_code=500, detail="failed to delete run")
    return {"status": "success", "detail": f"Run {run_id} deleted"}
