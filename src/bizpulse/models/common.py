"""Cross-cutting types: IDs, Tenant, Business, base config."""

from __future__ import annotations

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


# --- Domain entities ----------------------------------------------------------

class Tenant(StrictModel):
    id: TenantId = Field(default_factory=uuid4)
    name: str = Field(min_length=1)
    api_key: str = Field(min_length=8, description="Per-tenant API key for authentication.")
    created_at: datetime = Field(default_factory=utcnow)


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
