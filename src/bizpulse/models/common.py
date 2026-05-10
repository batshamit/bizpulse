"""Cross-cutting types: IDs, Tenant, Business, base config."""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

# --- ID types ----------------------------------------------------------------
# Stay as UUID for type safety. Postgres uses uuid columns; Qdrant payloads
# accept str, so we serialize via pydantic's default uuid handling.

TenantId = Annotated[UUID, Field(description="Tenant UUID — multi-tenant isolation key.")]
BusinessId = Annotated[UUID, Field(description="Business UUID — one company per row.")]
ChunkId = Annotated[UUID, Field(description="Chunk UUID — referenced in citations.")]
RunId = Annotated[UUID, Field(description="Run UUID — one analysis pipeline execution.")]


# --- Base ---------------------------------------------------------------------
# Strict by default. Extra fields fail loudly (catches YAML typos, drifted
# schemas, and unmapped LLM outputs). String fields strip whitespace.

class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
        frozen=False,
    )


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


# --- helpers ------------------------------------------------------------------

_SLUG_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str, *, suffix: bool = True) -> str:
    """Tenant-slug generator. Lowercase, dash-separated, optional 6-char suffix
    so two tenants named 'Acme' don't collide on the DB UNIQUE constraint."""
    base = _SLUG_NORMALIZE_RE.sub("-", name.lower()).strip("-")
    base = (base or "tenant")[:40]
    if not suffix:
        return base
    tail = secrets.token_urlsafe(6).lower().replace("_", "").replace("-", "")[:6] or "x"
    return f"{base}-{tail}"


# --- Domain entities ----------------------------------------------------------

class Tenant(StrictModel):
    id: TenantId = Field(default_factory=uuid4)
    name: str = Field(min_length=1)
    slug: Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*$")]
    api_key: str = Field(min_length=8, description="Per-tenant API key for authentication.")
    created_at: datetime = Field(default_factory=utcnow)
    daily_limit_override: int | None = Field(
        default=None,
        ge=0,
        description="Per-tenant override of the global daily analysis limit. None = inherit env default.",
    )
    suspended: bool = Field(
        default=False,
        description="When true, POST /analyze returns 403 regardless of quota.",
    )
    notes: str | None = Field(
        default=None,
        max_length=2000,
        description="Operator-only notes (visible only via admin endpoints).",
    )


SUPPORTED_INDUSTRIES: tuple[str, ...] = (
    "fintech",
    "real_estate",
    "construction_materials",
)


class Business(StrictModel):
    id: BusinessId = Field(default_factory=uuid4)
    tenant_id: TenantId
    url: str = Field(min_length=4, description="Canonical business website URL.")
    industry: str | None = Field(
        default=None,
        description="Industry slug (must match SUPPORTED_INDUSTRIES if set).",
    )
    status: str = Field(default="pending")
    created_at: datetime = Field(default_factory=utcnow)
