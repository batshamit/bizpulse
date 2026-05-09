"""Live tests for PostgresStore.

Skipped unless POSTGRES_PASSWORD is in the environment — local dev runs the
in-memory backend, the server runs against the real DB. Tests use unique
slugs per run so they don't fight the seeded 'demo' tenant.
"""

from __future__ import annotations

import os
import secrets

import pytest

from bizpulse.models import slugify
from bizpulse.storage.postgres import PostgresStore

pytestmark = pytest.mark.skipif(
    not os.environ.get("POSTGRES_PASSWORD"),
    reason="POSTGRES_PASSWORD not set — skip live PostgresStore tests",
)


@pytest.fixture
def store() -> PostgresStore:
    s = PostgresStore()
    yield s
    s.close()


def _uniq(prefix: str = "test") -> str:
    return f"{prefix}-{secrets.token_urlsafe(4).lower().replace('_','').replace('-','')[:6]}"


def test_create_and_lookup_tenant(store: PostgresStore) -> None:
    slug = _uniq("pg")
    tenant = store.create_tenant(name="pytest tenant", slug=slug)
    assert tenant.slug == slug
    assert tenant.api_key.startswith("bzp_")

    fetched = store.get_tenant(tenant.id)
    assert fetched is not None
    assert fetched.id == tenant.id

    by_key = store.get_tenant_by_api_key(tenant.api_key)
    assert by_key is not None
    assert by_key.id == tenant.id

    # bad key
    assert store.get_tenant_by_api_key("bzp_not-a-real-key") is None


def test_business_and_run_lifecycle(store: PostgresStore) -> None:
    tenant = store.create_tenant(name="pytest biz tenant", slug=_uniq("biz"))
    biz = store.create_business(tenant.id, url="https://test-biz.example", industry="fintech")
    assert biz.tenant_id == tenant.id
    assert biz.industry == "fintech"

    listed = store.list_businesses(tenant.id)
    assert biz.id in {b.id for b in listed}

    run = store.create_run(tenant.id, biz.id)
    assert run.status == "pending"
    assert run.tenant_id == tenant.id

    run2 = store.update_run_status(run.id, "complete")
    assert run2.status == "complete"
    assert run2.finished_at is not None

    runs = store.list_runs_for_business(biz.id)
    assert run.id in {r.id for r in runs}


def test_create_run_cross_tenant_rejected(store: PostgresStore) -> None:
    a = store.create_tenant(name="A", slug=_uniq("a"))
    b = store.create_tenant(name="B", slug=_uniq("b"))
    biz_a = store.create_business(a.id, url="https://a.example")
    with pytest.raises(ValueError, match="different tenant"):
        store.create_run(b.id, biz_a.id)


def test_seeded_demo_tenant_visible(store: PostgresStore) -> None:
    """init.sql seeds slug='demo'. We can find it by slug-style lookup
    (api key) — the seeded api_key is the well-known dev key."""
    demo = store.get_tenant_by_api_key("dev-demo-key-rotate-me")
    if demo is None:
        pytest.skip("demo seed not present in this DB")
    assert demo.slug == "demo"


def test_slugify_helper() -> None:
    s = slugify("Acme & Co.")
    assert s.startswith("acme-co-")
    assert all(c.isalnum() or c == "-" for c in s)
    # uniqueness
    assert slugify("Acme") != slugify("Acme")
