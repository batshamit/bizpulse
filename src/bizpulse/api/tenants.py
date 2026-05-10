"""Tenant CRUD endpoints.

Signup gating:
  POST /v1/tenants is open by default (standard SaaS signup pattern). If the
  env var `BIZPULSE_SIGNUP_CODE` is set, the request MUST include a matching
  `X-Signup-Code` header — useful when the public URL is exposed via a
  tunnel and you don't want random visitors burning LLM quota.
"""

from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from bizpulse.api.dependencies import get_store, require_tenant
from bizpulse.models import Tenant
from bizpulse.storage import Store

router = APIRouter(prefix="/v1/tenants", tags=["tenants"])


def _signup_code_required() -> str | None:
    """Returns the configured signup code, or None if signup is open."""
    code = os.environ.get("BIZPULSE_SIGNUP_CODE", "").strip()
    return code or None


def require_signup_code(
    x_signup_code: str | None = Header(default=None, alias="X-Signup-Code"),
) -> None:
    """Gate POST /v1/tenants behind a shared secret if BIZPULSE_SIGNUP_CODE
    is set. Use hmac.compare_digest for timing-safe comparison."""
    expected = _signup_code_required()
    if expected is None:
        return  # signup is open; no gating
    if not x_signup_code or not hmac.compare_digest(x_signup_code, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Signup requires a valid X-Signup-Code header. Ask the platform "
                "operator for the code."
            ),
            headers={"WWW-Authenticate": "SignupCode"},
        )


class CreateTenantRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9][a-z0-9-]*$",
        description="Optional URL-friendly identifier. Auto-generated from `name` if omitted.",
    )


@router.post(
    "",
    response_model=Tenant,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new tenant",
    description=(
        "Returns the new Tenant including its api_key. **Save the api_key** — "
        "it's only shown once and is used as `X-API-Key` on all subsequent "
        "calls. If `BIZPULSE_SIGNUP_CODE` is set on the server, the request "
        "must include a matching `X-Signup-Code` header."
    ),
)
def create_tenant(
    body: CreateTenantRequest,
    store: Store = Depends(get_store),
    _: None = Depends(require_signup_code),
) -> Tenant:
    return store.create_tenant(name=body.name, slug=body.slug)


@router.get(
    "/signup-policy",
    summary="Whether signup requires a code",
    description="Public endpoint the GUI calls to know if it should show the X-Signup-Code field on the 'New tenant' tab. Does not reveal the code itself.",
)
def signup_policy() -> dict[str, bool]:
    return {"requires_code": _signup_code_required() is not None}


@router.get(
    "/me",
    response_model=Tenant,
    summary="Current tenant (from X-API-Key)",
)
def whoami(tenant: Tenant = Depends(require_tenant)) -> Tenant:
    return tenant
