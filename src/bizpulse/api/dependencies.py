"""Shared FastAPI dependencies: auth, store accessor."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status

from bizpulse.models import Tenant
from bizpulse.storage import InMemoryStore, get_default_store


def get_store() -> InMemoryStore:
    return get_default_store()


def require_tenant(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    store: InMemoryStore = Depends(get_store),
) -> Tenant:
    """Auth: lookup tenant by API key from `X-API-Key` header.

    Returns the bound Tenant, or 401 if the key is missing/unknown.
    """
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    tenant = store.get_tenant_by_api_key(x_api_key)
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )
    return tenant
