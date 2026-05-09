"""In-memory tenant/business/run store.

Phase-9 scaffolding so FastAPI and MCP have a real-feeling storage surface
while Postgres init waits for an interactive sudo. The Postgres impl swaps in
later under the same `Store` protocol — no caller change needed.

Thread-safe (lock-protected) but not multi-process. Lost on restart. Fine for
demo/dev; the real persistence layer arrives in Phase 6/9 follow-up commits.
"""

from __future__ import annotations

import secrets
import threading
from uuid import UUID, uuid4

from bizpulse.models import (
    Business,
    BusinessId,
    RunRecord,
    RunStatus,
    Tenant,
    TenantId,
    slugify,
)
from bizpulse.models.common import utcnow


def _generate_api_key() -> str:
    return f"bzp_{secrets.token_urlsafe(24)}"


class InMemoryStore:
    """Stub store. The Postgres impl in `bizpulse.storage.postgres` mirrors
    this surface — callers can swap via env var (`BIZPULSE_STORE`)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tenants: dict[TenantId, Tenant] = {}
        self._tenants_by_api_key: dict[str, TenantId] = {}
        self._tenants_by_slug: dict[str, TenantId] = {}
        self._businesses: dict[BusinessId, Business] = {}
        self._businesses_by_tenant: dict[TenantId, list[BusinessId]] = {}
        self._runs: dict[UUID, RunRecord] = {}
        self._runs_by_business: dict[BusinessId, list[UUID]] = {}

    # ----- tenants -------------------------------------------------------

    def create_tenant(self, name: str, slug: str | None = None) -> Tenant:
        with self._lock:
            chosen_slug = slug or slugify(name)
            if chosen_slug in self._tenants_by_slug:
                raise ValueError(f"slug already in use: {chosen_slug}")
            tenant = Tenant(name=name, slug=chosen_slug, api_key=_generate_api_key())
            self._tenants[tenant.id] = tenant
            self._tenants_by_api_key[tenant.api_key] = tenant.id
            self._tenants_by_slug[tenant.slug] = tenant.id
            self._businesses_by_tenant.setdefault(tenant.id, [])
            return tenant

    def get_tenant(self, tenant_id: TenantId) -> Tenant | None:
        return self._tenants.get(tenant_id)

    def get_tenant_by_api_key(self, api_key: str) -> Tenant | None:
        with self._lock:
            tid = self._tenants_by_api_key.get(api_key)
            return self._tenants.get(tid) if tid else None

    def list_tenants(self) -> list[Tenant]:
        return list(self._tenants.values())

    # ----- businesses ----------------------------------------------------

    def create_business(
        self,
        tenant_id: TenantId,
        url: str,
        industry: str | None = None,
    ) -> Business:
        if tenant_id not in self._tenants:
            raise KeyError(f"unknown tenant: {tenant_id}")
        with self._lock:
            biz = Business(tenant_id=tenant_id, url=url, industry=industry)
            self._businesses[biz.id] = biz
            self._businesses_by_tenant.setdefault(tenant_id, []).append(biz.id)
            return biz

    def get_business(self, business_id: BusinessId) -> Business | None:
        return self._businesses.get(business_id)

    def list_businesses(self, tenant_id: TenantId) -> list[Business]:
        ids = self._businesses_by_tenant.get(tenant_id, [])
        return [self._businesses[b] for b in ids if b in self._businesses]

    # ----- runs ----------------------------------------------------------

    def create_run(self, tenant_id: TenantId, business_id: BusinessId) -> RunRecord:
        if tenant_id not in self._tenants:
            raise KeyError(f"unknown tenant: {tenant_id}")
        biz = self._businesses.get(business_id)
        if biz is None:
            raise KeyError(f"unknown business: {business_id}")
        if biz.tenant_id != tenant_id:
            raise ValueError("business belongs to a different tenant")
        with self._lock:
            run = RunRecord(
                id=uuid4(),
                tenant_id=tenant_id,
                business_id=business_id,
            )
            self._runs[run.id] = run
            self._runs_by_business.setdefault(business_id, []).append(run.id)
            return run

    def get_run(self, run_id: UUID) -> RunRecord | None:
        return self._runs.get(run_id)

    def update_run_status(
        self,
        run_id: UUID,
        status: RunStatus,
        *,
        error: str | None = None,
    ) -> RunRecord:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise KeyError(f"unknown run: {run_id}")
            run = run.model_copy(
                update={
                    "status": status,
                    "error": error,
                    "finished_at": utcnow() if status in {"complete", "failed"} else run.finished_at,
                }
            )
            self._runs[run_id] = run
            return run

    def list_runs_for_business(self, business_id: BusinessId) -> list[RunRecord]:
        ids = self._runs_by_business.get(business_id, [])
        return [self._runs[r] for r in ids if r in self._runs]

    # ----- diagnostics ---------------------------------------------------

    def stats(self) -> dict[str, int]:
        return {
            "tenants": len(self._tenants),
            "businesses": len(self._businesses),
            "runs": len(self._runs),
        }


# Singleton — replaced by a Postgres-backed impl in a later phase.
_default_store: InMemoryStore | None = None


def get_default_store() -> InMemoryStore:
    global _default_store
    if _default_store is None:
        _default_store = InMemoryStore()
    return _default_store


def reset_default_store_for_tests() -> None:
    """Test helper — wipes the singleton."""
    global _default_store
    _default_store = None
