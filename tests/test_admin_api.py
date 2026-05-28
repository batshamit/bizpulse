"""Unit and integration tests for administrative tenant deletion endpoints."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from bizpulse.api.main import app
from bizpulse.storage import get_default_store, reset_default_store_for_tests


@pytest.fixture(autouse=True)
def clean_store() -> None:
    reset_default_store_for_tests()


@pytest.fixture(autouse=True)
def setup_admin_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Setup admin key environment variables for testing admin routes."""
    monkeypatch.setenv("BIZPULSE_ADMIN_KEY", "test_admin_key")
    monkeypatch.delenv("BIZPULSE_ADMIN_TOTP_SECRET", raising=False)
    monkeypatch.delenv("BIZPULSE_SIGNUP_CODE", raising=False)


def test_delete_tenant_success() -> None:
    with TestClient(app) as client:
        # Create a tenant
        r_create = client.post("/v1/tenants", json={"name": "Temp Tenant"})
        assert r_create.status_code == 201
        tenant = r_create.json()
        tenant_id = tenant["id"]

        # Verify it exists in store
        store = get_default_store()
        assert store.get_tenant(UUID(tenant_id)) is not None

        # Delete it via admin endpoint
        r_delete = client.delete(
            f"/v1/admin/tenants/{tenant_id}",
            headers={"X-Admin-Key": "test_admin_key"},
        )
        assert r_delete.status_code == 200
        assert r_delete.json()["status"] == "success"

        # Verify it is deleted from the store
        assert store.get_tenant(UUID(tenant_id)) is None


def test_delete_tenant_not_found() -> None:
    with TestClient(app) as client:
        random_id = str(uuid4())
        r_delete = client.delete(
            f"/v1/admin/tenants/{random_id}",
            headers={"X-Admin-Key": "test_admin_key"},
        )
        assert r_delete.status_code == 404
        assert r_delete.json()["detail"] == "not found"


def test_delete_tenant_unauthorized() -> None:
    with TestClient(app) as client:
        # Create a tenant
        r_create = client.post("/v1/tenants", json={"name": "Temp Tenant"})
        assert r_create.status_code == 201
        tenant = r_create.json()
        tenant_id = tenant["id"]

        # Try deleting with missing header
        r_no_header = client.delete(f"/v1/admin/tenants/{tenant_id}")
        assert r_no_header.status_code == 401

        # Try deleting with incorrect header
        r_bad_header = client.delete(
            f"/v1/admin/tenants/{tenant_id}",
            headers={"X-Admin-Key": "wrong_key"},
        )
        assert r_bad_header.status_code == 401


def test_bulk_delete_tenants_success() -> None:
    with TestClient(app) as client:
        # Create three tenants
        t1 = client.post("/v1/tenants", json={"name": "T1"}).json()
        t2 = client.post("/v1/tenants", json={"name": "T2"}).json()
        t3 = client.post("/v1/tenants", json={"name": "T3"}).json()

        # Delete T1 and T2 via bulk delete
        r_bulk = client.post(
            "/v1/admin/tenants/bulk-delete",
            json={"tenant_ids": [t1["id"], t2["id"]]},
            headers={"X-Admin-Key": "test_admin_key"},
        )
        assert r_bulk.status_code == 200
        res = r_bulk.json()
        assert res["status"] == "success"
        assert res["deleted_count"] == 2

        deleted_ids = [item["id"] for item in res["deleted"]]
        assert t1["id"] in deleted_ids
        assert t2["id"] in deleted_ids

        # Check store
        store = get_default_store()
        assert store.get_tenant(UUID(t1["id"])) is None
        assert store.get_tenant(UUID(t2["id"])) is None
        assert store.get_tenant(UUID(t3["id"])) is not None


def test_bulk_delete_tenants_unauthorized() -> None:
    with TestClient(app) as client:
        t1 = client.post("/v1/tenants", json={"name": "T1"}).json()

        # Try without auth header
        r_bulk = client.post(
            "/v1/admin/tenants/bulk-delete",
            json={"tenant_ids": [t1["id"]]},
        )
        assert r_bulk.status_code == 401


def test_create_tenant_is_test() -> None:
    with TestClient(app) as client:
        # Default should be is_test=False
        r_default = client.post("/v1/tenants", json={"name": "Actual Tenant"})
        assert r_default.status_code == 201
        assert r_default.json()["is_test"] is False

        # Explicitly setting is_test=True
        r_test = client.post("/v1/tenants", json={"name": "Test Tenant", "is_test": True})
        assert r_test.status_code == 201
        assert r_test.json()["is_test"] is True


def test_update_tenant_is_test() -> None:
    with TestClient(app) as client:
        # Create actual tenant (is_test=False)
        r_create = client.post("/v1/tenants", json={"name": "Switch Tenant"})
        assert r_create.status_code == 201
        tenant = r_create.json()
        tenant_id = tenant["id"]
        assert tenant["is_test"] is False

        # Update it to is_test=True via admin patch
        r_patch = client.patch(
            f"/v1/admin/tenants/{tenant_id}",
            json={"is_test": True},
            headers={"X-Admin-Key": "test_admin_key"},
        )
        assert r_patch.status_code == 200
        assert r_patch.json()["is_test"] is True

        # Retrieve audit logs and verify the update was recorded
        r_audit = client.get(
            "/v1/admin/audit?limit=10",
            headers={"X-Admin-Key": "test_admin_key"},
        )
        assert r_audit.status_code == 200
        logs = r_audit.json()

        # Check that there is an update audit log with details for is_test
        update_log = next(
            (
                log
                for log in logs
                if log["action"] == "tenant.update" and log["target_id"] == tenant_id
            ),
            None,
        )
        assert update_log is not None
        assert "is_test" in update_log["details"]
        assert update_log["details"]["is_test"] == {"before": False, "after": True}


def test_bulk_update_tenants_success() -> None:
    with TestClient(app) as client:
        # Create three tenants
        t1 = client.post("/v1/tenants", json={"name": "Bulk T1"}).json()
        t2 = client.post("/v1/tenants", json={"name": "Bulk T2"}).json()
        t3 = client.post("/v1/tenants", json={"name": "Bulk T3"}).json()

        # Update limits and mark t1 and t2 as suspended and test tenants
        r_bulk = client.patch(
            "/v1/admin/tenants/bulk-patch",
            json={
                "tenant_ids": [t1["id"], t2["id"]],
                "update_limit": True,
                "daily_limit_override": 42,
                "update_suspended": True,
                "suspended": True,
                "update_is_test": True,
                "is_test": True,
                "update_notes": True,
                "notes": "Bulk operation notes",
            },
            headers={"X-Admin-Key": "test_admin_key"},
        )
        assert r_bulk.status_code == 200
        res = r_bulk.json()
        assert len(res) == 2

        # Verify changes in response
        for item in res:
            assert item["daily_limit_override"] == 42
            assert item["suspended"] is True
            assert item["is_test"] is True
            assert item["notes"] == "Bulk operation notes"

        # Verify database store state
        store = get_default_store()
        t1_store = store.get_tenant(UUID(t1["id"]))
        t2_store = store.get_tenant(UUID(t2["id"]))
        t3_store = store.get_tenant(UUID(t3["id"]))

        assert t1_store is not None
        assert t1_store.daily_limit_override == 42
        assert t1_store.suspended is True
        assert t1_store.is_test is True
        assert t1_store.notes == "Bulk operation notes"

        assert t2_store is not None
        assert t2_store.daily_limit_override == 42
        assert t2_store.suspended is True
        assert t2_store.is_test is True
        assert t2_store.notes == "Bulk operation notes"

        assert t3_store is not None
        assert t3_store.daily_limit_override is None
        assert t3_store.suspended is False
        assert t3_store.is_test is False
        assert t3_store.notes is None

        # Verify audit log is recorded
        r_audit = client.get(
            "/v1/admin/audit?limit=10",
            headers={"X-Admin-Key": "test_admin_key"},
        )
        assert r_audit.status_code == 200
        logs = r_audit.json()

        bulk_update_log = next(
            (log for log in logs if log["action"] == "tenant.bulk_update"),
            None,
        )
        assert bulk_update_log is not None
        assert "updated" in bulk_update_log["details"]
        updated_records = bulk_update_log["details"]["updated"]
        assert len(updated_records) == 2

        updated_ids = [r["id"] for r in updated_records]
        assert t1["id"] in updated_ids
        assert t2["id"] in updated_ids


def test_bulk_update_tenants_unauthorized() -> None:
    with TestClient(app) as client:
        t1 = client.post("/v1/tenants", json={"name": "Bulk T1"}).json()

        # Try without auth header
        r_bulk = client.patch(
            "/v1/admin/tenants/bulk-patch",
            json={
                "tenant_ids": [t1["id"]],
                "update_suspended": True,
                "suspended": True,
            },
        )
        assert r_bulk.status_code == 401
