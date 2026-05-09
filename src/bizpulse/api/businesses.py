"""Business CRUD + analyze endpoint."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from bizpulse.api.dependencies import get_store, require_tenant
from bizpulse.models import Business, RunRecord, Tenant
from bizpulse.models.common import SUPPORTED_INDUSTRIES
from bizpulse.storage import InMemoryStore

router = APIRouter(prefix="/v1/businesses", tags=["businesses"])


class CreateBusinessRequest(BaseModel):
    url: str = Field(min_length=4, max_length=2048)
    industry: str | None = Field(default=None)


@router.post(
    "",
    response_model=Business,
    status_code=status.HTTP_201_CREATED,
)
def create_business(
    body: CreateBusinessRequest,
    tenant: Tenant = Depends(require_tenant),
    store: InMemoryStore = Depends(get_store),
) -> Business:
    if body.industry is not None and body.industry not in SUPPORTED_INDUSTRIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unsupported industry; expected one of {SUPPORTED_INDUSTRIES}",
        )
    return store.create_business(tenant.id, url=body.url, industry=body.industry)


@router.get("", response_model=list[Business])
def list_businesses(
    tenant: Tenant = Depends(require_tenant),
    store: InMemoryStore = Depends(get_store),
) -> list[Business]:
    return store.list_businesses(tenant.id)


@router.get("/{business_id}", response_model=Business)
def get_business(
    business_id: UUID,
    tenant: Tenant = Depends(require_tenant),
    store: InMemoryStore = Depends(get_store),
) -> Business:
    biz = store.get_business(business_id)
    if biz is None or biz.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return biz


@router.post(
    "/{business_id}/analyze",
    response_model=RunRecord,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Kick off the analysis pipeline",
    description="Creates a RunRecord in `pending` state. The actual multi-agent pipeline lands in Phase 6 — this endpoint is the public contract that Phase 6 will fulfil.",
)
def analyze(
    business_id: UUID,
    tenant: Tenant = Depends(require_tenant),
    store: InMemoryStore = Depends(get_store),
) -> RunRecord:
    biz = store.get_business(business_id)
    if biz is None or biz.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return store.create_run(tenant.id, business_id)


@router.get("/{business_id}/runs", response_model=list[RunRecord])
def list_runs(
    business_id: UUID,
    tenant: Tenant = Depends(require_tenant),
    store: InMemoryStore = Depends(get_store),
) -> list[RunRecord]:
    biz = store.get_business(business_id)
    if biz is None or biz.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return store.list_runs_for_business(business_id)
