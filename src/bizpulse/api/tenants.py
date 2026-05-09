"""Tenant CRUD endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from bizpulse.api.dependencies import get_store, require_tenant
from bizpulse.models import Tenant
from bizpulse.storage import InMemoryStore

router = APIRouter(prefix="/v1/tenants", tags=["tenants"])


class CreateTenantRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


@router.post(
    "",
    response_model=Tenant,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new tenant",
    description="Returns the new Tenant including its api_key. **Save the api_key** — it's only shown once and is used as `X-API-Key` on all subsequent calls.",
)
def create_tenant(
    body: CreateTenantRequest,
    store: InMemoryStore = Depends(get_store),
) -> Tenant:
    return store.create_tenant(name=body.name)


@router.get(
    "/me",
    response_model=Tenant,
    summary="Current tenant (from X-API-Key)",
)
def whoami(tenant: Tenant = Depends(require_tenant)) -> Tenant:
    return tenant
