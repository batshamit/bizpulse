"""Run record lookup."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from bizpulse.api.dependencies import get_store, require_tenant
from bizpulse.models import RunRecord, Tenant
from bizpulse.storage import InMemoryStore

router = APIRouter(prefix="/v1/runs", tags=["runs"])


@router.get("/{run_id}", response_model=RunRecord)
def get_run(
    run_id: UUID,
    tenant: Tenant = Depends(require_tenant),
    store: InMemoryStore = Depends(get_store),
) -> RunRecord:
    run = store.get_run(run_id)
    if run is None or run.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return run
