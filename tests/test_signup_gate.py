"""Tests for the signup-code gate on POST /v1/tenants and the rate limit
on POST /analyze."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bizpulse.api.main import app
from bizpulse.storage import reset_default_store_for_tests


@pytest.fixture(autouse=True)
def clean_store() -> None:
    reset_default_store_for_tests()


# ---- signup-code gate ----------------------------------------------------


def test_signup_open_when_code_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BIZPULSE_SIGNUP_CODE", raising=False)
    with TestClient(app) as client:
        r = client.get("/v1/tenants/signup-policy")
        assert r.status_code == 200
        assert r.json() == {"requires_code": False}

        r = client.post("/v1/tenants", json={"name": "Open"})
        assert r.status_code == 201


def test_signup_gated_when_code_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BIZPULSE_SIGNUP_CODE", "demo-code")
    with TestClient(app) as client:
        assert client.get("/v1/tenants/signup-policy").json() == {"requires_code": True}

        # No code -> 401
        assert client.post("/v1/tenants", json={"name": "No code"}).status_code == 401

        # Wrong code -> 401
        r = client.post(
            "/v1/tenants",
            json={"name": "Wrong"},
            headers={"X-Signup-Code": "wrong"},
        )
        assert r.status_code == 401

        # Correct code -> 201
        r = client.post(
            "/v1/tenants",
            json={"name": "Correct"},
            headers={"X-Signup-Code": "demo-code"},
        )
        assert r.status_code == 201


# ---- daily rate limit ----------------------------------------------------


def test_daily_limit_blocks_after_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BIZPULSE_SIGNUP_CODE", raising=False)
    monkeypatch.setenv("BIZPULSE_DAILY_ANALYSIS_LIMIT", "2")
    with TestClient(app) as client:
        tenant = client.post("/v1/tenants", json={"name": "Limited"}).json()
        h = {"X-API-Key": tenant["api_key"]}
        biz = client.post(
            "/v1/businesses",
            json={"url": "https://example.test"},
            headers=h,
        ).json()

        # First 2 analyses succeed.
        assert client.post(f"/v1/businesses/{biz['id']}/analyze", headers=h).status_code == 202
        assert client.post(f"/v1/businesses/{biz['id']}/analyze", headers=h).status_code == 202
        # Third hits the gate.
        r = client.post(f"/v1/businesses/{biz['id']}/analyze", headers=h)
        assert r.status_code == 429
        assert "Retry-After" in r.headers
        body = r.json()
        assert "limit" in body["detail"].lower()


def test_daily_limit_disabled_when_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BIZPULSE_SIGNUP_CODE", raising=False)
    monkeypatch.setenv("BIZPULSE_DAILY_ANALYSIS_LIMIT", "0")
    with TestClient(app) as client:
        tenant = client.post("/v1/tenants", json={"name": "Unlimited"}).json()
        h = {"X-API-Key": tenant["api_key"]}
        biz = client.post(
            "/v1/businesses",
            json={"url": "https://example.test"},
            headers=h,
        ).json()
        # Many analyses, all succeed.
        for _ in range(5):
            assert client.post(f"/v1/businesses/{biz['id']}/analyze", headers=h).status_code == 202


# ---- usage endpoint ------------------------------------------------------


def test_usage_endpoint_reflects_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BIZPULSE_SIGNUP_CODE", raising=False)
    monkeypatch.setenv("BIZPULSE_DAILY_ANALYSIS_LIMIT", "5")
    with TestClient(app) as client:
        tenant = client.post("/v1/tenants", json={"name": "Counted"}).json()
        h = {"X-API-Key": tenant["api_key"]}
        biz = client.post(
            "/v1/businesses",
            json={"url": "https://example.test"},
            headers=h,
        ).json()

        r0 = client.get("/v1/tenants/me/usage", headers=h).json()
        assert r0["runs_today"] == 0
        assert r0["daily_limit"] == 5
        assert r0["remaining_today"] == 5

        client.post(f"/v1/businesses/{biz['id']}/analyze", headers=h)
        client.post(f"/v1/businesses/{biz['id']}/analyze", headers=h)

        r2 = client.get("/v1/tenants/me/usage", headers=h).json()
        assert r2["runs_today"] == 2
        assert r2["remaining_today"] == 3
