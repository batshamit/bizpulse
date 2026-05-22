"""Admin audit-log helpers + GET /v1/admin/audit endpoint.

The recording side (`record_audit`) is a synchronous best-effort write —
audit failures should never break the user-facing operation. If Postgres
is down we log a warning and proceed.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from bizpulse.api.admin import require_admin
from bizpulse.api.dependencies import get_store
from bizpulse.logging import get_logger
from bizpulse.storage import Store

log = get_logger(__name__)


def record_audit(
    *,
    store: Store,
    actor: str,
    action: str,
    target_kind: str | None = None,
    target_id: str | None = None,
    details: dict[str, Any] | None = None,
    request_ip: str | None = None,
) -> None:
    """Best-effort audit insert. Never raises."""
    try:
        store.insert_audit(
            actor=actor,
            action=action,
            target_kind=target_kind,
            target_id=target_id,
            details=details or {},
            request_ip=request_ip,
        )
    except Exception as exc:
        log.warning(
            "audit.write_failed",
            action=action,
            target_id=target_id,
            error=str(exc)[:200],
        )


# ---- GET /v1/admin/audit -------------------------------------------------

router = APIRouter(prefix="/v1/admin/audit", tags=["admin", "audit"])


@router.get("", summary="Recent admin audit-log entries (newest first)")
def list_audit(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: None = Depends(require_admin),
    store: Store = Depends(get_store),
) -> list[dict[str, Any]]:
    return store.list_audit(limit=limit, offset=offset)
