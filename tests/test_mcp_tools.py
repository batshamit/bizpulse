"""Tests for the MCP tool functions (no stdio — direct calls)."""

from __future__ import annotations

import pytest

from bizpulse.mcp import tools as t
from bizpulse.storage import reset_default_store_for_tests


@pytest.fixture(autouse=True)
def clean_store() -> None:
    reset_default_store_for_tests()


def test_register_tenant_returns_api_key() -> None:
    out = t.register_tenant("Acme")
    assert out["name"] == "Acme"
    assert out["api_key"].startswith("bzp_")


def test_whoami_round_trip() -> None:
    tenant = t.register_tenant("Acme")
    me = t.whoami(api_key=tenant["api_key"])
    assert me["id"] == tenant["id"]


def test_whoami_bad_key_raises() -> None:
    with pytest.raises(t.AuthError):
        t.whoami(api_key="bzp_garbage")


def test_industry_pack_lists_match_loaded_yaml() -> None:
    slugs = t.list_industries()
    assert "fintech" in slugs and "real_estate" in slugs
    pack = t.get_industry_pack("fintech")
    assert pack["slug"] == "fintech"
    assert "RBI" in str(pack)


def test_business_lifecycle() -> None:
    tenant = t.register_tenant("Acme")
    key = tenant["api_key"]

    biz = t.register_business(api_key=key, url="https://acme.com", industry="fintech")
    assert biz["url"] == "https://acme.com"

    listed = t.list_businesses(api_key=key)
    assert len(listed) == 1

    run = t.analyze_business(api_key=key, business_id=biz["id"])
    assert run["status"] == "pending"

    fetched = t.get_run(api_key=key, run_id=run["id"])
    assert fetched["id"] == run["id"]


def test_cross_tenant_business_lookup_404() -> None:
    a = t.register_tenant("A")
    b = t.register_tenant("B")
    biz = t.register_business(api_key=a["api_key"], url="https://a.com")
    with pytest.raises(t.NotFoundError):
        t.analyze_business(api_key=b["api_key"], business_id=biz["id"])


def test_query_knowledge_returns_status_pending() -> None:
    tenant = t.register_tenant("Acme")
    biz = t.register_business(api_key=tenant["api_key"], url="https://acme.com")
    out = t.query_business_knowledge(
        api_key=tenant["api_key"],
        business_id=biz["id"],
        question="What's the positioning?",
    )
    assert out["status"] == "not_implemented"
    assert out["chunks"] == []


def test_recommendations_pending_pipeline() -> None:
    tenant = t.register_tenant("Acme")
    biz = t.register_business(api_key=tenant["api_key"], url="https://acme.com")
    out = t.get_marketing_recommendations(
        api_key=tenant["api_key"],
        business_id=biz["id"],
        channel="linkedin",
    )
    assert out["status"] == "pending_pipeline"
    assert out["recommendations"] == []


def test_unsupported_industry_rejected() -> None:
    tenant = t.register_tenant("Acme")
    with pytest.raises(t.NotFoundError):
        t.register_business(api_key=tenant["api_key"], url="https://x.com", industry="blockchain")
