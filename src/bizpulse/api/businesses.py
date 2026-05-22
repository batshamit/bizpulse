"""Business CRUD + analyze endpoint."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field

from bizpulse.api.dependencies import get_store, require_tenant
from bizpulse.api.runner_service import run_analysis_background
from bizpulse.api.usage import enforce_daily_limit
from bizpulse.models import Business, RunRecord, Tenant
from bizpulse.models.common import SUPPORTED_INDUSTRIES
from bizpulse.storage import Store

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
    store: Store = Depends(get_store),
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
    store: Store = Depends(get_store),
) -> list[Business]:
    return store.list_businesses(tenant.id)


@router.get("/{business_id}", response_model=Business)
def get_business(
    business_id: UUID,
    tenant: Tenant = Depends(require_tenant),
    store: Store = Depends(get_store),
) -> Business:
    biz = store.get_business(business_id)
    if biz is None or biz.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return biz


class AnalyzeRequest(BaseModel):
    """Optional jurisdiction override and additional context for the run."""

    country: str = Field(default="IN", min_length=2, max_length=3)
    state: str | None = Field(default=None, max_length=64)
    additional_context: str | None = Field(default=None, max_length=10000)
    num_llms: int | None = Field(
        default=None, ge=1, le=5, description="Number of LLMs to include in the Council debate."
    )


@router.post(
    "/{business_id}/analyze",
    response_model=RunRecord,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Kick off the analysis pipeline",
    description=(
        "Creates a RunRecord in `pending` state and schedules a background "
        "task that crawls + chunks + embeds + runs the multi-agent LangGraph "
        "(council debate -> compliance audit). Poll /v1/runs/{id} for status; "
        "when status='complete', `final_output` carries the MarketingStrategy "
        "with embedded ComplianceReport."
    ),
)
def analyze(
    business_id: UUID,
    bg: BackgroundTasks,
    body: AnalyzeRequest | None = None,
    tenant: Tenant = Depends(enforce_daily_limit),
    store: Store = Depends(get_store),
) -> RunRecord:
    biz = store.get_business(business_id)
    if biz is None or biz.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    run = store.create_run(tenant.id, business_id)
    country = body.country if body else "IN"
    state = body.state if body else None
    context = body.additional_context if body else None
    num_llms = body.num_llms if body else None
    bg.add_task(
        run_analysis_background,
        run_id=run.id,
        business=biz,
        country=country,
        state=state,
        additional_context=context,
        num_llms=num_llms,
    )
    return run


@router.get("/{business_id}/runs", response_model=list[RunRecord])
def list_runs(
    business_id: UUID,
    tenant: Tenant = Depends(require_tenant),
    store: Store = Depends(get_store),
) -> list[RunRecord]:
    biz = store.get_business(business_id)
    if biz is None or biz.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return store.list_runs_for_business(business_id)
