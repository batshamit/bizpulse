"""Operator (admin) endpoints — visible to a single shared key, NOT a tenant.

Authentication: BIZPULSE_ADMIN_KEY env var. If BIZPULSE_ADMIN_TOTP_SECRET
is also set, requests must additionally pass a valid 6-digit TOTP code
in the X-Admin-TOTP header (Google Authenticator / 1Password / Authy
compatible). When TOTP is enabled, the key alone is insufficient.

Endpoints are namespaced under /v1/admin/ and gated by `require_admin`.
"""

from __future__ import annotations

import hmac
import os
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from bizpulse.config import settings
from bizpulse.api.dependencies import get_store
from bizpulse.api.usage import daily_limit
from bizpulse.models import Tenant
from bizpulse.models.common import utcnow
from bizpulse.models.industry import IndustryPack
from bizpulse.storage import Store

router = APIRouter(prefix="/v1/admin", tags=["admin"])


def _admin_key() -> str | None:
    raw = os.environ.get("BIZPULSE_ADMIN_KEY", "").strip()
    return raw or None


def _totp_secret() -> str | None:
    raw = os.environ.get("BIZPULSE_ADMIN_TOTP_SECRET", "").strip()
    return raw or None


def _verify_totp(code: str | None) -> bool:
    if not code:
        return False
    secret = _totp_secret()
    if not secret:
        return False
    try:
        import pyotp  # type: ignore[import-untyped]
    except ImportError:
        return False
    try:
        totp = pyotp.TOTP(secret)
        return bool(totp.verify(code, valid_window=1))
    except Exception:
        return False


def require_admin(
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
    x_admin_totp: str | None = Header(default=None, alias="X-Admin-TOTP"),
) -> None:
    expected = _admin_key()
    if expected is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin endpoints disabled — BIZPULSE_ADMIN_KEY not configured.",
        )
    if not x_admin_key or not hmac.compare_digest(x_admin_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid X-Admin-Key.",
            headers={"WWW-Authenticate": "AdminKey"},
        )
    if _totp_secret() is not None and not _verify_totp(x_admin_totp):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid TOTP code required (X-Admin-TOTP).",
            headers={"WWW-Authenticate": "AdminTOTP"},
        )


# --- response shapes -------------------------------------------------------


class TenantWithUsage(BaseModel):
    id: str
    name: str
    slug: str
    api_key: str
    created_at: str
    daily_limit_override: int | None
    suspended: bool
    notes: str | None
    is_test: bool
    runs_today: int
    runs_total: int
    effective_daily_limit: int
    total_cost_usd: float = 0.0


class UpdateTenantRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    daily_limit_override: int | None = Field(default=None, ge=0, le=10_000)
    clear_daily_limit_override: bool = Field(default=False)
    suspended: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)
    is_test: bool | None = None


class BulkDeleteRequest(BaseModel):
    tenant_ids: list[UUID]


class BulkUpdateTenantsRequest(BaseModel):
    tenant_ids: list[UUID]
    update_limit: bool = Field(default=False)
    daily_limit_override: int | None = Field(default=None, ge=0, le=10_000)
    clear_daily_limit_override: bool = Field(default=False)
    update_suspended: bool = Field(default=False)
    suspended: bool | None = None
    update_notes: bool = Field(default=False)
    notes: str | None = Field(default=None, max_length=2000)
    update_is_test: bool = Field(default=False)
    is_test: bool | None = None


class ImpersonateResponse(BaseModel):
    tenant_id: str
    name: str
    slug: str
    api_key: str


class AdminStatusResponse(BaseModel):
    enabled: bool
    requires_totp: bool = False


class CleanupRequest(BaseModel):
    pattern: str = Field(min_length=1, max_length=200)
    dry_run: bool = Field(default=True)
    confirm_token: str | None = Field(default=None)


class CleanupResponse(BaseModel):
    pattern: str
    dry_run: bool
    matched: list[dict]
    deleted_count: int


# ... existing code ...


@router.get("/proxy/{service}/{path:path}")
async def admin_proxy(
    service: str,
    path: str,
    _: None = Depends(require_admin),
) -> Response:
    """Proxy health checks to internal services."""
    urls = {
        "qdrant": settings.qdrant_url.rstrip("/"),
        "vllm": settings.llm_base_url.replace("/v1", ""),
        "tei-embed": settings.embed_base_url,
        "tei-rerank": settings.rerank_base_url,
    }
    if service not in urls:
        raise HTTPException(status_code=404, detail=f"Unknown service: {service}")

    service_base = urls[service].rstrip("/")
    target_path = path
    if path == "health" and ("11434" in service_base or "ollama" in service_base.lower()):
        target_path = ""

    target_url = f"{service_base}/{target_path}".rstrip("/")
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(target_url, timeout=2.0)
            return Response(
                content=r.content,
                status_code=r.status_code,
                media_type=r.headers.get("content-type"),
            )
        except Exception as e:
            raise HTTPException(
                status_code=502, detail=f"Service {service} unreachable: {e!s}"
            ) from e


@router.post("/processes/{pid}/terminate")
def terminate_process(pid: int, _: None = Depends(require_admin)) -> dict:
    """Attempt to terminate a process by PID."""
    import os
    import signal

    try:
        os.kill(pid, signal.SIGTERM)
        return {"status": "success", "detail": f"Signal sent to process {pid}"}
    except PermissionError:
        raise HTTPException(
            status_code=403,
            detail=f"Permission denied: You cannot kill process {pid} as it belongs to another user.",
        ) from None
    except ProcessLookupError:
        raise HTTPException(status_code=404, detail=f"Process {pid} not found.") from None
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/gpu")
def get_gpu_stats(_: None = Depends(require_admin)) -> dict:
    """Get live GPU utilization and memory stats, including processes and top users."""
    import subprocess

    stats = []
    user_mem: dict[str, int] = {}
    try:
        # 1. Map UUID to Index
        id_map = {}
        res_ids = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=index,uuid", "--format=csv,noheader"], text=True
        )
        for line in res_ids.strip().split("\n"):
            parts = [p.strip() for p in line.split(",")]
            if len(parts) == 2:
                id_map[parts[1]] = parts[0]

        # 2. Get User/Process info from system
        proc_owners = {}
        try:
            res_ps = subprocess.check_output(
                ["ps", "-e", "-o", "pid,user,comm", "--no-headers"], text=True
            )
            for line in res_ps.strip().split("\n"):
                parts = line.split(None, 2)
                if len(parts) >= 3:
                    proc_owners[parts[0]] = {"user": parts[1], "comm": parts[2]}
        except Exception:
            pass

        # 3. Get Compute Apps
        gpu_procs: dict[str, list[dict[str, Any]]] = {}
        try:
            res_apps = subprocess.check_output(
                [
                    "nvidia-smi",
                    "--query-compute-apps=gpu_uuid,pid,used_gpu_memory",
                    "--format=csv,noheader,nounits",
                ],
                text=True,
            )
            for line in res_apps.strip().split("\n"):
                parts = [p.strip() for p in line.split(",")]
                if len(parts) == 3:
                    uuid, pid, mem = parts
                    idx = id_map.get(uuid)
                    if idx:
                        if idx not in gpu_procs:
                            gpu_procs[idx] = []
                        owner = proc_owners.get(pid, {"user": "unknown", "comm": "unknown"})
                        gpu_procs[idx].append(
                            {
                                "pid": pid,
                                "user": owner["user"],
                                "comm": owner["comm"],
                                "mem": f"{mem} MiB",
                            }
                        )
                        # Aggregate by user
                        user = owner["user"]
                        user_mem[user] = user_mem.get(user, 0) + int(mem)
        except Exception:
            pass

        # 4. Get GPU main stats
        res = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,memory.used,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            text=True,
        )
        for line in res.strip().split("\n"):
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 5:
                stats.append(
                    {
                        "index": parts[0],
                        "name": parts[1],
                        "total": f"{parts[2]} MiB",
                        "used": f"{parts[3]} MiB",
                        "util": int(parts[4]),
                        "processes": gpu_procs.get(parts[0], []),
                    }
                )
    except Exception:
        pass

    # Sort top users
    top_users: list[dict[str, Any]] = [{"user": u, "mem": f"{m} MiB", "raw_mem": m} for u, m in user_mem.items()]
    top_users.sort(key=lambda x: int(x["raw_mem"]), reverse=True)

    return {"gpus": stats, "top_users": top_users[:10]}


@router.get("/storage")
def get_storage_stats(_: None = Depends(require_admin)) -> list[dict]:
    """Get disk usage for key partitions."""
    import subprocess

    stats = []
    try:
        # Run df for /raid and / (root)
        res = subprocess.check_output(["df", "-h", "/raid", "/"], text=True)
        lines = res.strip().split("\n")[1:]  # skip header
        for line in lines:
            parts = line.split()
            if len(parts) >= 6:
                stats.append(
                    {
                        "mount": parts[5],
                        "total": parts[1],
                        "used": parts[2],
                        "free": parts[3],
                        "percent": int(parts[4].replace("%", "")),
                    }
                )
    except Exception:
        pass
    return stats


# --- routes ----------------------------------------------------------------


@router.get("/status", response_model=AdminStatusResponse)
def admin_status() -> AdminStatusResponse:
    return AdminStatusResponse(
        enabled=_admin_key() is not None,
        requires_totp=_totp_secret() is not None,
    )


def _to_tenant_with_usage(t: Tenant, store: Store) -> TenantWithUsage:
    window_start = utcnow() - timedelta(hours=24)
    runs_today = store.count_runs_for_tenant_since(t.id, window_start)
    runs_total = store.count_runs_for_tenant(t.id)
    effective_limit = (
        t.daily_limit_override if t.daily_limit_override is not None else daily_limit()
    )
    cost_total = 0.0
    try:
        usage = store.usage_for_tenant(t.id)
        cost_total = float(usage.get("total_cost_usd", 0.0) or 0.0)
    except Exception:
        pass
    return TenantWithUsage(
        id=str(t.id),
        name=t.name,
        slug=t.slug,
        api_key=t.api_key,
        created_at=t.created_at.isoformat(),
        daily_limit_override=t.daily_limit_override,
        suspended=t.suspended,
        notes=t.notes,
        is_test=t.is_test,
        runs_today=runs_today,
        runs_total=runs_total,
        effective_daily_limit=effective_limit,
        total_cost_usd=cost_total,
    )


@router.get("/tenants", response_model=list[TenantWithUsage])
def list_tenants(
    _: None = Depends(require_admin),
    store: Store = Depends(get_store),
) -> list[TenantWithUsage]:
    return [_to_tenant_with_usage(t, store) for t in store.list_tenants()]


@router.patch("/tenants/bulk-patch", response_model=list[TenantWithUsage])
def bulk_patch_tenants(
    body: BulkUpdateTenantsRequest,
    request: Request,
    _: None = Depends(require_admin),
    store: Store = Depends(get_store),
) -> list[TenantWithUsage]:
    from bizpulse.api.audit import record_audit

    updated_tenants = []
    audit_details = []

    for tid in body.tenant_ids:
        before = store.get_tenant(tid)
        if before is None:
            continue

        kwargs: dict[str, Any] = {}
        if body.update_limit:
            kwargs["clear_daily_limit_override"] = body.clear_daily_limit_override
            if not body.clear_daily_limit_override:
                kwargs["daily_limit_override"] = body.daily_limit_override
        if body.update_suspended:
            kwargs["suspended"] = body.suspended
        if body.update_notes:
            kwargs["notes"] = body.notes
        if body.update_is_test:
            kwargs["is_test"] = body.is_test

        if not kwargs:
            updated_tenants.append(_to_tenant_with_usage(before, store))
            continue

        updated = store.update_tenant(tid, **kwargs)
        if updated is not None:
            updated_tenants.append(_to_tenant_with_usage(updated, store))
            diff: dict[str, Any] = {}
            if body.update_limit:
                new_val = None if body.clear_daily_limit_override else body.daily_limit_override
                if before.daily_limit_override != new_val:
                    diff["daily_limit_override"] = {"before": before.daily_limit_override, "after": new_val}
            if body.update_suspended and before.suspended != body.suspended:
                diff["suspended"] = {"before": before.suspended, "after": body.suspended}
            if body.update_notes and before.notes != body.notes:
                diff["notes"] = {"before": before.notes, "after": body.notes}
            if body.update_is_test and before.is_test != body.is_test:
                diff["is_test"] = {"before": before.is_test, "after": body.is_test}
            
            if diff:
                audit_details.append({"id": str(tid), "name": before.name, "diff": diff})

    if audit_details:
        record_audit(
            store=store,
            actor="admin",
            action="tenant.bulk_update",
            target_kind="tenant",
            target_id="bulk",
            details={"updated": audit_details},
            request_ip=request.client.host if request.client else None,
        )

    return updated_tenants


@router.patch("/tenants/{tenant_id}", response_model=TenantWithUsage)
def update_tenant(
    tenant_id: UUID,
    body: UpdateTenantRequest,
    request: Request,
    _: None = Depends(require_admin),
    store: Store = Depends(get_store),
) -> TenantWithUsage:
    from bizpulse.api.audit import record_audit

    before = store.get_tenant(tenant_id)
    updated = store.update_tenant(
        tenant_id,
        name=body.name,
        daily_limit_override=body.daily_limit_override,
        clear_daily_limit_override=body.clear_daily_limit_override,
        suspended=body.suspended,
        notes=body.notes,
        is_test=body.is_test,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="not found")
    if before is not None:
        diff: dict[str, object] = {}
        for field in ("name", "daily_limit_override", "suspended", "notes", "is_test"):
            old_v = getattr(before, field)
            new_v = getattr(updated, field)
            if old_v != new_v:
                diff[field] = {"before": old_v, "after": new_v}
        if diff:
            record_audit(
                store=store,
                actor="admin",
                action="tenant.update",
                target_kind="tenant",
                target_id=str(tenant_id),
                details=diff,
                request_ip=request.client.host if request.client else None,
            )
    return _to_tenant_with_usage(updated, store)


@router.delete("/tenants/{tenant_id}", status_code=status.HTTP_200_OK)
def delete_tenant(
    tenant_id: UUID,
    request: Request,
    _: None = Depends(require_admin),
    store: Store = Depends(get_store),
) -> dict:
    from bizpulse.api.audit import record_audit

    before = store.get_tenant(tenant_id)
    if before is None:
        raise HTTPException(status_code=404, detail="not found")
    
    success = store.delete_tenant(tenant_id)
    if not success:
        raise HTTPException(status_code=500, detail="failed to delete tenant")

    record_audit(
        store=store,
        actor="admin",
        action="tenant.delete",
        target_kind="tenant",
        target_id=str(tenant_id),
        details={"name": before.name, "slug": before.slug},
        request_ip=request.client.host if request.client else None,
    )
    return {"status": "success", "detail": f"Tenant {tenant_id} deleted"}


@router.post("/tenants/bulk-delete", status_code=status.HTTP_200_OK)
def bulk_delete_tenants(
    body: BulkDeleteRequest,
    request: Request,
    _: None = Depends(require_admin),
    store: Store = Depends(get_store),
) -> dict:
    from bizpulse.api.audit import record_audit

    deleted = []
    for tid in body.tenant_ids:
        before = store.get_tenant(tid)
        if before is not None and store.delete_tenant(tid):
            deleted.append({"id": str(tid), "name": before.name})

    if deleted:
        record_audit(
            store=store,
            actor="admin",
            action="tenant.bulk_delete",
            target_kind="tenant",
            target_id="bulk",
            details={"deleted": deleted},
            request_ip=request.client.host if request.client else None,
        )
    return {"status": "success", "deleted_count": len(deleted), "deleted": deleted}


@router.post("/tenants/cleanup", response_model=CleanupResponse)
def cleanup_tenants(
    body: CleanupRequest,
    request: Request,
    _: None = Depends(require_admin),
    store: Store = Depends(get_store),
) -> CleanupResponse:
    from bizpulse.api.audit import record_audit

    if not body.dry_run and body.confirm_token != "DELETE":
        raise HTTPException(
            status_code=400, detail="confirm_token must equal 'DELETE' when dry_run=false."
        )
    try:
        if body.dry_run:
            matched = store.find_tenants_by_name_regex(body.pattern)
            deleted = 0
        else:
            matched = store.delete_tenants_by_name_regex(body.pattern)
            deleted = len(matched)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"cleanup failed: {exc!s}") from exc
    if not body.dry_run:
        record_audit(
            store=store,
            actor="admin",
            action="tenant.cleanup",
            target_kind="tenant",
            target_id=body.pattern,
            details={"deleted_count": deleted, "matched_names": [m["name"] for m in matched[:50]]},
            request_ip=request.client.host if request.client else None,
        )
    return CleanupResponse(
        pattern=body.pattern, dry_run=body.dry_run, matched=matched, deleted_count=deleted
    )


@router.post("/tenants/{tenant_id}/impersonate", response_model=ImpersonateResponse)
def impersonate(
    tenant_id: UUID,
    request: Request,
    _: None = Depends(require_admin),
    store: Store = Depends(get_store),
) -> ImpersonateResponse:
    from bizpulse.api.audit import record_audit

    t = store.get_tenant(tenant_id)
    if t is None:
        raise HTTPException(status_code=404, detail="not found")
    record_audit(
        store=store,
        actor="admin",
        action="tenant.impersonate",
        target_kind="tenant",
        target_id=str(tenant_id),
        details={"name": t.name, "slug": t.slug},
        request_ip=request.client.host if request.client else None,
    )
    return ImpersonateResponse(tenant_id=str(t.id), name=t.name, slug=t.slug, api_key=t.api_key)


# --- metadata management --------------------------------------------------


@router.get("/metadata/locations", summary="Get locations metadata")
def get_admin_locations(_: None = Depends(require_admin)) -> dict:
    from bizpulse.api.industries import _load_locations

    return _load_locations()


@router.post("/metadata/locations", summary="Save locations metadata")
def save_admin_locations(body: dict, _: None = Depends(require_admin)) -> dict:
    import json
    from pathlib import Path

    data_dir = Path(__file__).resolve().parents[3] / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    with (data_dir / "locations.json").open("w", encoding="utf-8") as f:
        json.dump(body, f, indent=2)
    return body


# --- industry management --------------------------------------------------


@router.get("/industries", summary="List industry packs")
def list_industries(_: None = Depends(require_admin)) -> list[dict]:
    from bizpulse.models.industry import load_all_industries

    all_packs = load_all_industries()
    return [p.model_dump() for p in all_packs.values()]


@router.post("/industries", summary="Create/Update an industry pack")
def save_industry(pack: IndustryPack, _: None = Depends(require_admin)) -> IndustryPack:
    import yaml

    base = Path(__file__).resolve().parents[3] / "industries"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{pack.slug}.yaml"
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(pack.model_dump(), fh)
    return pack


@router.delete("/industries/{slug}", summary="Delete an industry pack")
def delete_industry(slug: str, _: None = Depends(require_admin)) -> dict:
    base = Path(__file__).resolve().parents[3] / "industries"
    path = base / f"{slug}.yaml"
    if path.is_file():
        path.unlink()
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="not found")
