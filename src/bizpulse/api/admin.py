"""Operator (admin) endpoints — visible to a single shared key, NOT a tenant.

Authentication: BIZPULSE_ADMIN_KEY env var. If BIZPULSE_ADMIN_TOTP_SECRET
is also set, requests must additionally pass a valid 6-digit TOTP code
in the X-Admin-TOTP header (Google Authenticator / 1Password / Authy
compatible). When TOTP is enabled, the key alone is insufficient.

Why a separate key (not an "admin tenant"): operators aren't tenants, and
we don't want admin-level powers tied to a tenant row that an attacker
who breached that tenant's api_key could exploit. The admin key is held
only by the platform operator.

Endpoints are namespaced under /v1/admin/ and gated by `require_admin`.
"""

from __future__ import annotations

import hmac
import os
from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from bizpulse.api.dependencies import get_store
from bizpulse.api.usage import daily_limit
from bizpulse.models import Tenant
from bizpulse.models.common import utcnow
from bizpulse.storage import Store

router = APIRouter(prefix="/v1/admin", tags=["admin"])


def _admin_key() -> str | None:
    raw = os.environ.get("BIZPULSE_ADMIN_KEY", "").strip()
    return raw or None


def _totp_secret() -> str | None:
    raw = os.environ.get("BIZPULSE_ADMIN_TOTP_SECRET", "").strip()
    return raw or None


def _verify_totp(code: str | None) -> bool:
    """Verify a TOTP code against the configured secret. Returns False on
    bad code, missing pyotp, or absent secret. The caller decides what to
    do with the result."""
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
    except Exception:  # noqa: BLE001
        return False


def require_admin(
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
    x_admin_totp: str | None = Header(default=None, alias="X-Admin-TOTP"),
) -> None:
    """Block requests that don't carry the operator's admin key.

    If BIZPULSE_ADMIN_KEY isn't set, all admin endpoints return 503 with a
    clear message — we don't want to silently expose them when misconfigured.

    If BIZPULSE_ADMIN_TOTP_SECRET is set, X-Admin-TOTP must also pass.
    """
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
    """Admin's view of a tenant — includes usage and the suspended flag."""

    id: str
    name: str
    slug: str
    api_key: str
    created_at: str
    daily_limit_override: int | None
    suspended: bool
    notes: str | None
    runs_today: int
    runs_total: int
    effective_daily_limit: int
    total_cost_usd: float = 0.0


class UpdateTenantRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    daily_limit_override: int | None = Field(default=None, ge=0, le=10_000)
    clear_daily_limit_override: bool = Field(
        default=False,
        description="Pass true to explicitly clear the override (revert to global default).",
    )
    suspended: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)


class ImpersonateResponse(BaseModel):
    tenant_id: str
    name: str
    slug: str
    api_key: str


class AdminStatusResponse(BaseModel):
    enabled: bool
    """Whether BIZPULSE_ADMIN_KEY is configured. Public — does not reveal the key."""

    requires_totp: bool = False
    """Whether BIZPULSE_ADMIN_TOTP_SECRET is set; the GUI uses this to show
    the TOTP field."""


class TenantUsageDetail(BaseModel):
    total_cost_usd: float
    total_input_tokens: int
    total_output_tokens: int
    llm_call_count: int
    runs_total: int


class CleanupRequest(BaseModel):
    """Bulk-delete tenants whose name matches a POSIX regex."""

    pattern: str = Field(min_length=1, max_length=200, description="POSIX regex; matched against tenants.name (case-sensitive).")
    dry_run: bool = Field(default=True, description="If true, return matches without deleting.")
    confirm_token: str | None = Field(default=None, description="Required (must equal 'DELETE') when dry_run=false.")


class CleanupResponse(BaseModel):
    pattern: str
    dry_run: bool
    matched: list[dict]
    deleted_count: int


# --- routes ----------------------------------------------------------------

@router.get(
    "/status",
    response_model=AdminStatusResponse,
    summary="Whether admin endpoints are enabled",
    description="Public health-check the GUI uses to decide whether to surface the Admin tab on the login page.",
)
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
    except Exception:  # noqa: BLE001 — pre-migration storage may not have it
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
        runs_today=runs_today,
        runs_total=runs_total,
        effective_daily_limit=effective_limit,
        total_cost_usd=cost_total,
    )


@router.get(
    "/tenants",
    response_model=list[TenantWithUsage],
    summary="List every tenant with current usage",
)
def list_tenants(
    _: None = Depends(require_admin),
    store: Store = Depends(get_store),
) -> list[TenantWithUsage]:
    return [_to_tenant_with_usage(t, store) for t in store.list_tenants()]


@router.get(
    "/tenants/{tenant_id}",
    response_model=TenantWithUsage,
    summary="Single tenant detail (admin view)",
)
def get_tenant(
    tenant_id: UUID,
    _: None = Depends(require_admin),
    store: Store = Depends(get_store),
) -> TenantWithUsage:
    t = store.get_tenant(tenant_id)
    if t is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return _to_tenant_with_usage(t, store)


@router.patch(
    "/tenants/{tenant_id}",
    response_model=TenantWithUsage,
    summary="Update tenant: name / daily_limit_override / suspended / notes",
)
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
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    if before is not None:
        diff: dict[str, object] = {}
        for field in ("name", "daily_limit_override", "suspended", "notes"):
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


@router.delete(
    "/tenants/{tenant_id}",
    summary="Delete a single tenant (cascades to businesses + runs)",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_tenant(
    tenant_id: UUID,
    request: Request,
    _: None = Depends(require_admin),
    store: Store = Depends(get_store),
) -> None:
    from bizpulse.api.audit import record_audit
    t = store.get_tenant(tenant_id)
    if t is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    ok = store.delete_tenant(tenant_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    record_audit(
        store=store,
        actor="admin",
        action="tenant.delete",
        target_kind="tenant",
        target_id=str(tenant_id),
        details={"name": t.name, "slug": t.slug},
        request_ip=request.client.host if request.client else None,
    )


@router.post(
    "/tenants/cleanup",
    response_model=CleanupResponse,
    summary="Bulk-delete tenants by name regex (dry_run by default)",
    description=(
        "POSIX regex matched against `tenants.name`. dry_run=true (default) "
        "returns matches without deleting. Set dry_run=false AND "
        "confirm_token='DELETE' to actually remove them. Cascades to all "
        "businesses + runs + run_steps via FK ON DELETE CASCADE."
    ),
)
def cleanup_tenants(
    body: CleanupRequest,
    request: Request,
    _: None = Depends(require_admin),
    store: Store = Depends(get_store),
) -> CleanupResponse:
    from bizpulse.api.audit import record_audit

    if not body.dry_run and body.confirm_token != "DELETE":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="confirm_token must equal 'DELETE' when dry_run=false.",
        )

    try:
        if body.dry_run:
            matched = store.find_tenants_by_name_regex(body.pattern)
            deleted = 0
        else:
            matched = store.delete_tenants_by_name_regex(body.pattern)
            deleted = len(matched)
    except Exception as exc:  # noqa: BLE001 — bad regex / SQL error
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"cleanup failed: {exc!s}",
        )

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
        pattern=body.pattern,
        dry_run=body.dry_run,
        matched=matched,
        deleted_count=deleted,
    )


@router.post(
    "/tenants/{tenant_id}/impersonate",
    response_model=ImpersonateResponse,
    summary="Return a tenant's api_key so the operator can sign in as them",
    description=(
        "Operator UX: lets you debug a user's report or kick off an analysis "
        "on their behalf. The returned api_key is what the GUI swaps into "
        "localStorage so the dashboard renders that tenant's view. The GUI "
        "shows a yellow 'Impersonating X' banner during the session."
    ),
)
def impersonate(
    tenant_id: UUID,
    request: Request,
    _: None = Depends(require_admin),
    store: Store = Depends(get_store),
) -> ImpersonateResponse:
    from bizpulse.api.audit import record_audit
    t = store.get_tenant(tenant_id)
    if t is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    record_audit(
        store=store,
        actor="admin",
        action="tenant.impersonate",
        target_kind="tenant",
        target_id=str(tenant_id),
        details={"name": t.name, "slug": t.slug},
        request_ip=request.client.host if request.client else None,
    )
    return ImpersonateResponse(
        tenant_id=str(t.id),
        name=t.name,
        slug=t.slug,
        api_key=t.api_key,
    )
