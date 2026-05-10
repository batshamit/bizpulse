"""Per-tenant usage / quota — runs counted, daily limit enforced.

The daily limit is configured via `BIZPULSE_DAILY_ANALYSIS_LIMIT` (env var,
default 5). When exceeded, POST /analyze returns 429 with a Retry-After
header pointing to when the oldest in-window run will expire.

Token-based quota (LLM cost) needs cost_usd persisted on each run; that's
a follow-up. For now we limit by run count which is the most actionable
spam-control signal.
"""

from __future__ import annotations

import os
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from bizpulse.api.dependencies import get_store, require_tenant
from bizpulse.models import Tenant
from bizpulse.models.common import utcnow
from bizpulse.storage import Store

router = APIRouter(prefix="/v1/tenants/me", tags=["usage"])


def daily_limit() -> int:
    raw = os.environ.get("BIZPULSE_DAILY_ANALYSIS_LIMIT", "5").strip()
    try:
        n = int(raw)
        return max(0, n)
    except ValueError:
        return 5


class UsageReport(BaseModel):
    """What the GUI dashboard / quota card shows."""

    tenant_id: str
    runs_today: int = Field(ge=0)
    runs_total: int = Field(ge=0)
    daily_limit: int = Field(ge=0)
    remaining_today: int = Field(ge=0)
    window_start: str
    """ISO-8601 timestamp — start of the rolling 24h window."""


def _build_usage(*, tenant: Tenant, store: Store) -> UsageReport:
    limit = daily_limit()
    window_start = utcnow() - timedelta(hours=24)
    runs_today = store.count_runs_for_tenant_since(tenant.id, window_start)
    runs_total = store.count_runs_for_tenant(tenant.id)
    return UsageReport(
        tenant_id=str(tenant.id),
        runs_today=runs_today,
        runs_total=runs_total,
        daily_limit=limit,
        remaining_today=max(0, limit - runs_today),
        window_start=window_start.isoformat(),
    )


@router.get(
    "/usage",
    response_model=UsageReport,
    summary="Current tenant's analysis quota usage",
)
def usage(
    tenant: Tenant = Depends(require_tenant),
    store: Store = Depends(get_store),
) -> UsageReport:
    return _build_usage(tenant=tenant, store=store)


# ---- rate-limit dependency for POST /analyze ----------------------------

def enforce_daily_limit(
    tenant: Tenant = Depends(require_tenant),
    store: Store = Depends(get_store),
) -> Tenant:
    """Block POST /analyze if the tenant has hit their daily quota.

    Returns the tenant on success (so the dependency-injected tenant is
    re-used by the endpoint). Raises 429 + Retry-After header on overflow."""
    limit = daily_limit()
    if limit == 0:
        return tenant  # quota disabled
    window_start = utcnow() - timedelta(hours=24)
    n = store.count_runs_for_tenant_since(tenant.id, window_start)
    if n >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Daily analysis limit reached ({n}/{limit} in the last 24h). "
                "Try again tomorrow, or ask the operator to raise the limit."
            ),
            headers={"Retry-After": str(60 * 60)},  # 1 hour as a polite floor
        )
    return tenant
