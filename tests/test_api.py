"""End-to-end FastAPI tests using the in-memory store."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bizpulse.api.main import app
from bizpulse.storage import reset_default_store_for_tests


@pytest.fixture(autouse=True)
def clean_store() -> None:
    reset_default_store_for_tests()


@pytest.fixture(autouse=True)
def open_signup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable the signup-code gate for these tests so direct POSTs work
    without a header. The gate itself is covered by tests/test_signup_gate.py."""
    monkeypatch.delenv("BIZPULSE_SIGNUP_CODE", raising=False)


@pytest.fixture(autouse=True)
def open_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable the daily quota for these tests (analyze should always work)."""
    monkeypatch.setenv("BIZPULSE_DAILY_ANALYSIS_LIMIT", "0")


def test_root_and_healthz() -> None:
    with TestClient(app) as client:
        assert client.get("/healthz").json()["status"] == "ok"
        # /api is the new JSON service-info endpoint; / redirects to /ui/
        assert client.get("/api").json()["service"] == "bizpulse"
        # / is now a redirect to the static GUI
        r = client.get("/", follow_redirects=False)
        assert r.status_code in (302, 307)
        assert "/ui" in r.headers.get("location", "")


def test_tenant_create_and_whoami() -> None:
    with TestClient(app) as client:
        r = client.post("/v1/tenants", json={"name": "Acme Demo"})
        assert r.status_code == 201
        tenant = r.json()
        assert tenant["name"] == "Acme Demo"
        api_key = tenant["api_key"]
        assert api_key.startswith("bzp_")

        r2 = client.get("/v1/tenants/me", headers={"X-API-Key": api_key})
        assert r2.status_code == 200
        assert r2.json()["id"] == tenant["id"]


def test_whoami_requires_api_key() -> None:
    with TestClient(app) as client:
        assert client.get("/v1/tenants/me").status_code == 401
        assert client.get("/v1/tenants/me", headers={"X-API-Key": "bzp_garbage"}).status_code == 401


def test_business_lifecycle() -> None:
    with TestClient(app) as client:
        tenant = client.post("/v1/tenants", json={"name": "Acme"}).json()
        h = {"X-API-Key": tenant["api_key"]}

        # bad industry rejected
        r = client.post(
            "/v1/businesses",
            json={"url": "https://example.com", "industry": "blockchain"},
            headers=h,
        )
        assert r.status_code == 422

        # good
        r = client.post(
            "/v1/businesses",
            json={"url": "https://acme-fintech.com", "industry": "fintech"},
            headers=h,
        )
        assert r.status_code == 201
        biz = r.json()
        assert biz["url"] == "https://acme-fintech.com"
        assert biz["tenant_id"] == tenant["id"]

        # reference document uploads are supported and fully functional
        dummy_file = ("dummy.txt", b"Hello world, this is a test reference document for Acme.", "text/plain")
        r = client.post(
            f"/v1/businesses/{biz['id']}/documents",
            files={"file": dummy_file},
            headers=h,
        )
        assert r.status_code == 201
        doc = r.json()
        assert doc["filename"] == "dummy.txt"
        assert doc["content_type"] == "text/plain"
        assert doc["n_chunks"] > 0

        # documents can be listed
        r = client.get(f"/v1/businesses/{biz['id']}/documents", headers=h)
        assert r.status_code == 200
        docs = r.json()
        assert len(docs) == 1
        assert docs[0]["id"] == doc["id"]

        # documents can be deleted cleanly
        r = client.delete(f"/v1/businesses/{biz['id']}/documents/{doc['id']}", headers=h)
        assert r.status_code == 204

        # list reflects deletion
        r = client.get(f"/v1/businesses/{biz['id']}/documents", headers=h)
        assert r.status_code == 200
        assert len(r.json()) == 0

        # list reflects creation
        r = client.get("/v1/businesses", headers=h)
        assert r.status_code == 200
        assert len(r.json()) == 1

        # analyze creates a run in pending state
        r = client.post(f"/v1/businesses/{biz['id']}/analyze", headers=h)
        assert r.status_code == 202
        run = r.json()
        assert run["status"] == "pending"
        assert run["business_id"] == biz["id"]

        # run lookup
        r = client.get(f"/v1/runs/{run['id']}", headers=h)
        assert r.status_code == 200
        assert r.json()["id"] == run["id"]


def test_cross_tenant_business_access_404() -> None:
    """Tenant A cannot read tenant B's business via guess-the-uuid."""
    with TestClient(app) as client:
        a = client.post("/v1/tenants", json={"name": "A"}).json()
        b = client.post("/v1/tenants", json={"name": "B"}).json()

        biz = client.post(
            "/v1/businesses",
            json={"url": "https://a.com"},
            headers={"X-API-Key": a["api_key"]},
        ).json()

        # B tries to read A's biz
        r = client.get(
            f"/v1/businesses/{biz['id']}",
            headers={"X-API-Key": b["api_key"]},
        )
        assert r.status_code == 404


def test_downloads_and_chat_endpoints() -> None:
    from unittest.mock import AsyncMock, patch
    from uuid import UUID, uuid4

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
    from bizpulse.models.compliance import ComplianceFlag, ComplianceReport, LLLLMetric
    from bizpulse.storage import get_default_store

    with TestClient(app) as client:
        # Create tenants
        tenant_a = client.post("/v1/tenants", json={"name": "Tenant A"}).json()
        tenant_b = client.post("/v1/tenants", json={"name": "Tenant B"}).json()

        headers_a = {"X-API-Key": tenant_a["api_key"]}
        headers_b = {"X-API-Key": tenant_b["api_key"]}

        # Create business for Tenant A
        biz = client.post(
            "/v1/businesses",
            json={"url": "https://example.com", "industry": "fintech"},
            headers=headers_a,
        ).json()

        # Create a run in the store manually so we can set final_output
        store = get_default_store()
        run = store.create_run(UUID(tenant_a["id"]), UUID(biz["id"]))
        run_id = run.id

        # Construct a valid MarketingStrategy
        cid = uuid4()
        strategy = MarketingStrategy(
            tenant_id=UUID(tenant_a["id"]),
            business_id=UUID(biz["id"]),
            industry="fintech",
            brand=BrandAnalysis(
                positioning="Test positioning",
                tone="formal",
                value_props=["quick setup"],
                citations=[Citation(chunk_id=cid)],
            ),
            audience=AudienceAnalysis(
                primary=AudiencePersona(
                    name="Test Audience",
                    description="Standard test persona",
                    citations=[Citation(chunk_id=cid)],
                ),
                citations=[Citation(chunk_id=cid)],
            ),
            competitive_landscape=CompetitiveLandscape(
                competitors=[
                    Competitor(
                        name="Comp A",
                        url="https://compa.com",
                        positioning="cheap",
                        verified=True,
                        citations=[Citation(chunk_id=cid)],
                    )
                ],
                market_position="average",
                citations=[Citation(chunk_id=cid)],
            ),
            content_audit=ContentAudit(),
            recommendations=[
                Recommendation(
                    channel="linkedin",
                    action="Publish case studies",
                    rationale="Audience reads case studies",
                    evidence_chunk_ids=[cid],
                    confidence=0.9,
                    priority="P0",
                )
            ],
            inclusivity_metrics=LLLLMetric(
                last=0.8,
                least=0.7,
                lost=0.6,
                lowest=0.5,
                narrative="Good test metrics",
            ),
            overall_confidence=0.85,
            summary="A test summary of the marketing strategy.",
            benefit_report="Benefit of the strategy.",
            compliance_report=ComplianceReport(
                country="IN",
                state="maharashtra",
                policies_considered=["rera-maharashtra"],
                flags=[
                    ComplianceFlag(
                        policy_slug="rera-maharashtra",
                        severity="warning",
                        issue="missing disclosures",
                        fix="add disclaimer",
                    )
                ],
                metrics=LLLLMetric(
                    last=0.8,
                    least=0.7,
                    lost=0.6,
                    lowest=0.5,
                    narrative="Good test metrics",
                ),
                overall_compliance_score=0.9,
                summary="Overall compliant with warning",
            ),
        )

        # Complete the run with final output
        store.update_run_status(run_id, "complete")
        from bizpulse.api.runner_service import _persist_final_output

        _persist_final_output(store=store, run_id=run_id, strategy=strategy)

        # 1. Test GET /v1/runs/{run_id}/pdf
        r_pdf = client.get(f"/v1/runs/{run_id}/pdf", headers=headers_a)
        assert r_pdf.status_code == 200

        assert r_pdf.headers["content-type"] == "application/pdf"
        assert f"BizPulse_Report_{run_id}.pdf" in r_pdf.headers["content-disposition"]
        assert len(r_pdf.content) > 0

        # Test cross-tenant access to pdf
        r_pdf_b = client.get(f"/v1/runs/{run_id}/pdf", headers=headers_b)
        assert r_pdf_b.status_code == 404

        # 2. Test GET /v1/runs/{run_id}/download (Markdown)
        r_md = client.get(f"/v1/runs/{run_id}/download", headers=headers_a)
        assert r_md.status_code == 200
        assert r_md.headers["content-type"] == "text/markdown; charset=utf-8"
        assert f"BizPulse_Report_{run_id}.md" in r_md.headers["content-disposition"]
        assert "# BizPulse Marketing Strategy Report" in r_md.text
        assert "Inclusivity Scorecard (4 L's)" in r_md.text
        assert "Compliance Audit" in r_md.text

        # Test cross-tenant access to markdown download
        r_md_b = client.get(f"/v1/runs/{run_id}/download", headers=headers_b)
        assert r_md_b.status_code == 404

        # 3. Test POST /v1/runs/{run_id}/chat
        chat_req = {
            "recommendation_index": 0,
            "message": "Can you elaborate on publishing case studies?",
        }

        with patch(
            "bizpulse.api.runs.chat_about_recommendation", new_callable=AsyncMock
        ) as mock_chat:
            mock_chat.return_value = "This is a detailed mock implementation reply."

            r_chat = client.post(f"/v1/runs/{run_id}/chat", json=chat_req, headers=headers_a)
            assert r_chat.status_code == 200
            assert r_chat.json() == {"reply": "This is a detailed mock implementation reply."}
            mock_chat.assert_called_once()

        # Test cross-tenant access to chat
        r_chat_b = client.post(f"/v1/runs/{run_id}/chat", json=chat_req, headers=headers_b)
        assert r_chat_b.status_code == 404

        # 4. Test Daily Research Report downloads and chat rejection
        from bizpulse.models import DailyResearchReport

        run_dr = store.create_run(UUID(tenant_a["id"]), UUID(biz["id"]), run_type="daily_research")
        run_dr_id = run_dr.id

        from bizpulse.models import (
            AcademicPaper,
            BusinessDeal,
            CompetitiveIntelligenceOutput,
            EnvironmentalMonitorOutput,
            PolicyAnalystOutput,
        )

        dr_report = DailyResearchReport(
            tenant_id=UUID(tenant_a["id"]),
            business_id=UUID(biz["id"]),
            industry="fintech",
            most_important_update="This is a test critical update.",
            academic_research=[
                AcademicPaper(
                    title="Smart Fintech AI Paper",
                    key_findings="AI improves transaction routing.",
                    business_application="Deploy router.",
                )
            ],
            policy_and_politics=PolicyAnalystOutput(
                regulatory=["RBI policy changes"],
                financial=["Taxes updated"],
                geopolitical=[],
                citations=[Citation(chunk_id=cid, quote="Test quote", confidence=0.9)],
            ),
            business_deals=[
                BusinessDeal(
                    entities="Fintech Corp & Bank",
                    strategic_impact="Expanded dealer network.",
                )
            ],
            climate_and_weather=EnvironmentalMonitorOutput(
                threats=[],
                opportunities=["Green data centers reduce carbon footprint."],
                citations=[],
            ),
            competitors_and_products=CompetitiveIntelligenceOutput(
                new_products=["Launch of Product X"],
                competitor_moves=["Competitor Y pivot."],
                client_sentiment=[],
                citations=[],
            ),
            emerging_radar=["Adjacent sector growth anomaly."],
            uncertainty_log=["Uncertain price changes"],
            overall_confidence=0.95,
            citations=[Citation(chunk_id=cid, quote="Test quote", confidence=0.9)],
        )
        store.update_run_status(run_dr_id, "complete")
        _persist_final_output(store=store, run_id=run_dr_id, strategy=dr_report)

        # Test PDF download for daily research
        r_pdf_dr = client.get(f"/v1/runs/{run_dr_id}/pdf", headers=headers_a)
        assert r_pdf_dr.status_code == 200
        assert r_pdf_dr.headers["content-type"] == "application/pdf"
        assert f"BizPulse_Report_{run_dr_id}.pdf" in r_pdf_dr.headers["content-disposition"]
        assert len(r_pdf_dr.content) > 0

        # Test Markdown download for daily research
        r_md_dr = client.get(f"/v1/runs/{run_dr_id}/download", headers=headers_a)
        assert r_md_dr.status_code == 200
        assert r_md_dr.headers["content-type"] == "text/markdown; charset=utf-8"
        assert f"BizPulse_Report_{run_dr_id}.md" in r_md_dr.headers["content-disposition"]
        assert "# BizPulse Daily Research Report" in r_md_dr.text
        assert "Launch of Product X" in r_md_dr.text
        assert "RBI policy changes" in r_md_dr.text
        assert "Uncertain price changes" in r_md_dr.text
        assert "Source #1" in r_md_dr.text

        # Test POST /v1/runs/{run_dr_id}/chat should fail with 400 for daily research
        r_chat_dr = client.post(f"/v1/runs/{run_dr_id}/chat", json=chat_req, headers=headers_a)
        assert r_chat_dr.status_code == 400
        assert "only supported for marketing strategy" in r_chat_dr.json()["detail"]

        # Test DELETE /v1/runs/{run_dr_id} endpoint successfully deletes the run
        r_del = client.delete(f"/v1/runs/{run_dr_id}", headers=headers_a)
        assert r_del.status_code == 200
        assert r_del.json()["status"] == "success"

        # Verify that it is deleted and returns 404
        r_get = client.get(f"/v1/runs/{run_dr_id}", headers=headers_a)
        assert r_get.status_code == 404

        # Test cross-tenant deletion failure (Tenant B tries to delete a Tenant A run)
        run_dr_2 = store.create_run(UUID(tenant_a["id"]), UUID(biz["id"]), run_type="daily_research")
        run_dr_2_id = run_dr_2.id

        r_del_b = client.delete(f"/v1/runs/{run_dr_2_id}", headers=headers_b)
        assert r_del_b.status_code == 404
