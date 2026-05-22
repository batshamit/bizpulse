"""Cross-cutting types: IDs, Tenant, Business, base config."""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

# --- ID types ----------------------------------------------------------------
TenantId = Annotated[UUID, Field(description="Tenant UUID — multi-tenant isolation key.")]
BusinessId = Annotated[UUID, Field(description="Business UUID — one company per row.")]
ChunkId = Annotated[UUID, Field(description="Chunk UUID — referenced in citations.")]
RunId = Annotated[UUID, Field(description="Run UUID — one analysis pipeline execution.")]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
        frozen=False,
    )


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


_SLUG_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str, *, suffix: bool = True) -> str:
    base = _SLUG_NORMALIZE_RE.sub("-", name.lower()).strip("-")
    base = (base or "tenant")[:40]
    if not suffix:
        return base
    tail = secrets.token_urlsafe(6).lower().replace("_", "").replace("-", "")[:6] or "x"
    return f"{base}-{tail}"


class Tenant(StrictModel):
    id: TenantId = Field(default_factory=uuid4)
    name: str = Field(min_length=1)
    slug: Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*$")]
    api_key: str = Field(min_length=8, description="Per-tenant API key for authentication.")
    created_at: datetime = Field(default_factory=utcnow)
    daily_limit_override: int | None = Field(default=None, ge=0)
    suspended: bool = Field(default=False)
    notes: str | None = Field(default=None, max_length=2000)


def _get_supported_industries() -> tuple[str, ...]:
    """Scan the industries/ directory for .yaml files to determine supported slugs."""
    base = Path(__file__).resolve().parents[3] / "industries"
    if not base.is_dir():
        return ("fintech", "real_estate", "construction_materials")
    slugs = [p.stem for p in base.glob("*.yaml") if p.is_file()]
    return tuple(sorted(slugs)) if slugs else ("fintech", "real_estate", "construction_materials")


class _DynamicSupportedIndustries:
    def __contains__(self, item: object) -> bool:
        return item in _get_supported_industries()

    def __iter__(self):
        return iter(_get_supported_industries())

    def __len__(self) -> int:
        return len(_get_supported_industries())

    def __repr__(self) -> str:
        return repr(_get_supported_industries())

    def __getitem__(self, idx):
        return _get_supported_industries()[idx]


SUPPORTED_INDUSTRIES = _DynamicSupportedIndustries()


class Business(StrictModel):
    id: BusinessId = Field(default_factory=uuid4)
    tenant_id: TenantId
    url: str = Field(min_length=4)
    industry: str | None = Field(default=None)
    status: str = Field(default="pending")
    created_at: datetime = Field(default_factory=utcnow)
