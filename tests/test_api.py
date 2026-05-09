"""End-to-end FastAPI tests using the in-memory store."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bizpulse.api.main import app
from bizpulse.storage import reset_default_store_for_tests


@pytest.fixture(autouse=True)
def clean_store() -> None:
    reset_default_store_for_tests()


def test_root_and_healthz() -> None:
    with TestClient(app) as client:
        assert client.get("/healthz").json()["status"] == "ok"
        assert client.get("/").json()["service"] == "bizpulse"


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
        assert client.get(
            "/v1/tenants/me", headers={"X-API-Key": "bzp_garbage"}
        ).status_code == 401


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
