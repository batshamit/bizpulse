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
from datetime import datetime
from typing import Literal
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

    def create_tenant(self, name: str, slug: str | None = None, is_test: bool = False) -> Tenant:
        with self._lock:
            chosen_slug = slug or slugify(name)
            if chosen_slug in self._tenants_by_slug:
                raise ValueError(f"slug already in use: {chosen_slug}")
            tenant = Tenant(
                name=name, slug=chosen_slug, api_key=_generate_api_key(), is_test=is_test
            )
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

    def usage_for_tenant(self, tenant_id: TenantId) -> dict[str, float | int]:
        cost = 0.0
        in_tok = 0
        out_tok = 0
        calls = 0
        for r in self._runs.values():
            if r.tenant_id != tenant_id:
                continue
            cost += r.total_cost_usd
            in_tok += r.total_input_tokens
            out_tok += r.total_output_tokens
            calls += r.llm_call_count
        return {
            "total_cost_usd": cost,
            "total_input_tokens": in_tok,
            "total_output_tokens": out_tok,
            "llm_call_count": calls,
        }

    def update_run_usage(
        self,
        run_id: UUID,
        *,
        cost_usd: float,
        input_tokens: int,
        output_tokens: int,
        llm_calls: int,
    ) -> None:
        with self._lock:
            r = self._runs.get(run_id)
            if r is None:
                return
            self._runs[run_id] = r.model_copy(
                update={
                    "total_cost_usd": cost_usd,
                    "total_input_tokens": input_tokens,
                    "total_output_tokens": output_tokens,
                    "llm_call_count": llm_calls,
                }
            )

    def delete_tenant(self, tenant_id: TenantId) -> bool:
        with self._lock:
            t = self._tenants.pop(tenant_id, None)
            if t is None:
                return False
            self._tenants_by_api_key.pop(t.api_key, None)
            self._tenants_by_slug.pop(t.slug, None)
            biz_ids = self._businesses_by_tenant.pop(tenant_id, [])
            for bid in biz_ids:
                self._businesses.pop(bid, None)
                run_ids = self._runs_by_business.pop(bid, [])
                for rid in run_ids:
                    self._runs.pop(rid, None)
            return True

    def find_tenants_by_name_regex(self, pattern: str) -> list[dict]:
        import re

        try:
            rx = re.compile(pattern)
        except re.error:
            return []
        return [
            {"id": str(t.id), "name": t.name, "slug": t.slug}
            for t in sorted(self._tenants.values(), key=lambda x: x.created_at)
            if rx.search(t.name)
        ]

    def delete_tenants_by_name_regex(self, pattern: str) -> list[dict]:
        targets = self.find_tenants_by_name_regex(pattern)
        for t in targets:
            self.delete_tenant(UUID(t["id"]))
        return targets

    # ----- audit log (in-memory) ----------------------------------------

    # ----- reference documents (in-memory) -----------------------------

    def insert_document(self, **kw) -> dict:
        from datetime import datetime as _dt
        if not hasattr(self, "_documents"):
            self._documents: list[dict] = []
        # dedup by (business_id, sha256)
        for d in self._documents:
            if d["business_id"] == str(kw["business_id"]) and d["sha256"] == kw["sha256"]:
                return {k: v for k, v in d.items() if k != "business_id" and k != "tenant_id"}
        rec = {
            "id": str(kw["id"]),
            "tenant_id": str(kw["tenant_id"]),
            "business_id": str(kw["business_id"]),
            "filename": kw["filename"],
            "content_type": kw["content_type"],
            "size_bytes": kw["size_bytes"],
            "n_chunks": kw["n_chunks"],
            "sha256": kw["sha256"],
            "extracted_chars": kw.get("extracted_chars", 0),
            "uploaded_at": _dt.now().isoformat(),
        }
        self._documents.append(rec)
        return {k: v for k, v in rec.items() if k not in ("business_id", "tenant_id")}

    def find_document_by_sha(self, business_id: BusinessId, sha256: str) -> dict | None:
        if not hasattr(self, "_documents"):
            return None
        for d in self._documents:
            if d["business_id"] == str(business_id) and d["sha256"] == sha256:
                return {k: v for k, v in d.items() if k not in ("business_id", "tenant_id")}
        return None

    def list_documents(self, business_id: BusinessId) -> list[dict]:
        if not hasattr(self, "_documents"):
            return []
        return [
            {k: v for k, v in d.items() if k not in ("business_id", "tenant_id")}
            for d in self._documents if d["business_id"] == str(business_id)
        ]

    def delete_document(self, business_id: BusinessId, document_id: UUID) -> bool:
        if not hasattr(self, "_documents"):
            return False
        before = len(self._documents)
        self._documents = [
            d for d in self._documents
            if not (d["business_id"] == str(business_id) and d["id"] == str(document_id))
        ]
        return len(self._documents) < before

    def insert_audit(self, **kw) -> UUID:
        from datetime import datetime as _dt
        from uuid import uuid4 as _u4

        rec = {
            "id": str(_u4()),
            "occurred_at": _dt.now().isoformat(),
            "actor": kw.get("actor", ""),
            "action": kw.get("action", ""),
            "target_kind": kw.get("target_kind"),
            "target_id": kw.get("target_id"),
            "details": kw.get("details") or {},
            "request_ip": kw.get("request_ip"),
        }
        if not hasattr(self, "_audit"):
            self._audit: list[dict] = []
        self._audit.append(rec)
        return UUID(rec["id"])

    def list_audit(self, *, limit: int = 100, offset: int = 0) -> list[dict]:
        if not hasattr(self, "_audit"):
            return []
        items = list(reversed(self._audit))
        return items[offset : offset + limit]

    def update_tenant(
        self,
        tenant_id: TenantId,
        *,
        name: str | None = None,
        daily_limit_override: int | None = None,
        clear_daily_limit_override: bool = False,
        suspended: bool | None = None,
        notes: str | None = None,
        is_test: bool | None = None,
    ) -> Tenant | None:
        with self._lock:
            t = self._tenants.get(tenant_id)
            if t is None:
                return None
            updates: dict[str, object] = {}
            if name is not None:
                updates["name"] = name
            if clear_daily_limit_override:
                updates["daily_limit_override"] = None
            elif daily_limit_override is not None:
                updates["daily_limit_override"] = daily_limit_override
            if suspended is not None:
                updates["suspended"] = suspended
            if notes is not None:
                updates["notes"] = notes
            if is_test is not None:
                updates["is_test"] = is_test
            if not updates:
                return t
            new_t = t.model_copy(update=updates)
            self._tenants[tenant_id] = new_t
            return new_t

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

    def create_run(
        self,
        tenant_id: TenantId,
        business_id: BusinessId,
        run_type: str = "marketing_strategy",
        inputs: dict | None = None,
    ) -> RunRecord:
        # Verify the business belongs to this tenant before writing the run.
        biz = self.get_business(business_id)
        if biz is None:
            raise KeyError(f"unknown business: {business_id}")
        if biz.tenant_id != tenant_id:
            raise ValueError("business belongs to a different tenant")
        import socket
        import os
        with self._lock:
            run = RunRecord(
                id=uuid4(),
                tenant_id=tenant_id,
                business_id=business_id,
                run_type=run_type,
                inputs=inputs,
                hostname=socket.gethostname(),
                pid=os.getpid(),
                last_heartbeat_at=utcnow(),
            )
            self._runs[run.id] = run
            self._runs_by_business.setdefault(business_id, []).append(run.id)
            return run

    def delete_run(self, run_id: UUID) -> bool:
        with self._lock:
            run = self._runs.pop(run_id, None)
            if run is None:
                return False
            biz_runs = self._runs_by_business.get(run.business_id, [])
            if run_id in biz_runs:
                biz_runs.remove(run_id)
            return True

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
                    "finished_at": (
                        utcnow() if status in {"complete", "failed"} else run.finished_at
                    ),
                }
            )
            self._runs[run_id] = run
            return run

    def add_agent_trace(self, run_id: UUID, status: RunStatus, trace: object) -> None:
        """Append an AgentTrace and update status in-memory."""
        with self._lock:
            if run_id in self._runs:
                run = self._runs[run_id]
                traces = list(run.agent_traces or [])
                # Remove duplicate
                traces = [t for t in traces if getattr(t, "agent", None) != getattr(trace, "agent", None)]
                traces.append(trace)
                
                # Also put in final_output if final_output exists
                final_output = run.final_output
                if final_output:
                    try:
                        final_output = final_output.model_copy(update={"agent_traces": traces})
                    except Exception:
                        pass
                
                self._runs[run_id] = run.model_copy(
                    update={
                        "status": status,
                        "agent_traces": traces,
                        "final_output": final_output
                    }
                )

    def list_runs_for_business(self, business_id: BusinessId) -> list[RunRecord]:
        ids = self._runs_by_business.get(business_id, [])
        return [self._runs[r] for r in ids if r in self._runs]

    def get_successful_runs_by_industry(self, industry: str, limit: int = 3) -> list[RunRecord]:
        out = []
        with self._lock:
            for run in self._runs.values():
                if run.status == "complete":
                    biz = self._businesses.get(run.business_id)
                    if biz and biz.industry == industry:
                        out.append(run)
        out.sort(key=lambda r: r.finished_at or r.started_at, reverse=True)
        return out[:limit]

    def count_runs_for_tenant_since(self, tenant_id: TenantId, since: datetime) -> int:
        """Number of runs created by this tenant after `since`. Used for
        rate-limiting POST /analyze."""
        n = 0
        for run in self._runs.values():
            if run.tenant_id == tenant_id and run.started_at >= since:
                n += 1
        return n

    def count_runs_for_tenant(self, tenant_id: TenantId) -> int:
        return sum(1 for r in self._runs.values() if r.tenant_id == tenant_id)

    # ----- diagnostics ---------------------------------------------------

    def stats(self) -> dict[str, int]:
        return {
            "tenants": len(self._tenants),
            "businesses": len(self._businesses),
            "runs": len(self._runs),
        }

    def fail_orphaned_runs(self) -> int:
        """Find any runs that are currently in a non-terminal state and mark them as failed."""
        import socket
        import os
        from datetime import timedelta
        count = 0
        current_hostname = socket.gethostname()
        current_pid = os.getpid()
        cutoff = utcnow() - timedelta(minutes=2)
        with self._lock:
            for run_id, run in list(self._runs.items()):
                if run.status not in {"complete", "failed"}:
                    is_local_zombie = (
                        run.hostname == current_hostname
                        and (run.pid is None or run.pid != current_pid)
                    )
                    is_timeout_zombie = (
                        run.last_heartbeat_at is None or run.last_heartbeat_at < cutoff
                    )
                    if is_local_zombie or is_timeout_zombie:
                        self._runs[run_id] = run.model_copy(
                             update={
                                 "status": "failed",
                                 "error": "Run aborted due to server restart/reload",
                                 "finished_at": utcnow(),
                             }
                        )
                        count += 1
        return count

    def heartbeat_run(self, run_id: UUID, hostname: str, pid: int) -> None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return
            self._runs[run_id] = run.model_copy(
                update={
                    "hostname": hostname,
                    "pid": pid,
                    "last_heartbeat_at": utcnow(),
                }
            )


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
