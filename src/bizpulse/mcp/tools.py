"""Tool functions exposed by the BizPulse MCP server.

These are plain Python functions; the MCP server (`bizpulse.mcp.server`)
wraps them with `@mcp.tool()`. Splitting the wiring lets tests call the
tools directly without a stdio round-trip.

API-key authentication mirrors the FastAPI surface — every tool that touches
a tenant's data takes `api_key` as its first arg and looks up the tenant via
the store. Cross-tenant lookups return a NotFoundError rather than leaking
existence.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from bizpulse.models import (
    Business,
    RunRecord,
    SUPPORTED_INDUSTRIES,
    Tenant,
    load_all_industries,
    load_industry,
)
from bizpulse.storage import InMemoryStore, get_default_store


class AuthError(RuntimeError):
    """Bad / missing api_key."""


class NotFoundError(RuntimeError):
    """Resource doesn't exist or doesn't belong to the caller's tenant."""


# --- helpers ------------------------------------------------------------

def _store() -> InMemoryStore:
    return get_default_store()


def _resolve_tenant(api_key: str) -> Tenant:
    if not api_key:
        raise AuthError("api_key is required")
    tenant = _store().get_tenant_by_api_key(api_key)
    if tenant is None:
        raise AuthError("invalid api_key")
    return tenant


def _resolve_business(tenant: Tenant, business_id: str) -> Business:
    bid = UUID(business_id) if isinstance(business_id, str) else business_id
    biz = _store().get_business(bid)
    if biz is None or biz.tenant_id != tenant.id:
        raise NotFoundError(f"business {business_id} not found for this tenant")
    return biz


# --- tenant tools -------------------------------------------------------

def register_tenant(name: str) -> dict[str, Any]:
    """Create a new tenant. Returns the api_key (only shown once)."""
    tenant = _store().create_tenant(name)
    return tenant.model_dump(mode="json")


def whoami(api_key: str) -> dict[str, Any]:
    """Return the tenant bound to this api_key."""
    return _resolve_tenant(api_key).model_dump(mode="json")


# --- industry catalog ---------------------------------------------------

def list_industries() -> list[str]:
    """Names of supported industry verticals."""
    return list(SUPPORTED_INDUSTRIES)


def get_industry_pack(slug: str) -> dict[str, Any]:
    """Return the full IndustryPack YAML as a dict (entities, regulations,
    competitor seeds, channel weights, content pillars, prompt addendum)."""
    if slug not in SUPPORTED_INDUSTRIES:
        raise NotFoundError(f"unsupported industry: {slug}")
    return load_industry(slug).model_dump(mode="json")


def list_industry_packs() -> dict[str, dict[str, Any]]:
    return {k: v.model_dump(mode="json") for k, v in load_all_industries().items()}


# --- business tools -----------------------------------------------------

def register_business(api_key: str, url: str, industry: str | None = None) -> dict[str, Any]:
    tenant = _resolve_tenant(api_key)
    if industry is not None and industry not in SUPPORTED_INDUSTRIES:
        raise NotFoundError(f"unsupported industry: {industry}")
    biz = _store().create_business(tenant.id, url=url, industry=industry)
    return biz.model_dump(mode="json")


def list_businesses(api_key: str) -> list[dict[str, Any]]:
    tenant = _resolve_tenant(api_key)
    return [b.model_dump(mode="json") for b in _store().list_businesses(tenant.id)]


# --- pipeline tools -----------------------------------------------------

def analyze_business(api_key: str, business_id: str) -> dict[str, Any]:
    """Kick off the multi-agent pipeline for a business. Returns a RunRecord
    in `pending` state. The actual pipeline lands in Phase 6 — this tool is
    the public contract Phase 6 will fulfil."""
    tenant = _resolve_tenant(api_key)
    biz = _resolve_business(tenant, business_id)
    run = _store().create_run(tenant.id, biz.id)
    return run.model_dump(mode="json")


def get_run(api_key: str, run_id: str) -> dict[str, Any]:
    tenant = _resolve_tenant(api_key)
    rid = UUID(run_id) if isinstance(run_id, str) else run_id
    run = _store().get_run(rid)
    if run is None or run.tenant_id != tenant.id:
        raise NotFoundError(f"run {run_id} not found for this tenant")
    return run.model_dump(mode="json")


def list_runs_for_business(api_key: str, business_id: str) -> list[dict[str, Any]]:
    tenant = _resolve_tenant(api_key)
    biz = _resolve_business(tenant, business_id)
    return [r.model_dump(mode="json") for r in _store().list_runs_for_business(biz.id)]


# --- knowledge query (RAG) ---------------------------------------------
# query_business_knowledge() needs a real embedder. In Phase 8 we ship the
# tool wired to RetrievalEngine but it returns an explanatory error if TEI
# isn't running. Phase 6/9 follow-up wires a real fallback (Anthropic
# embeddings).

def query_business_knowledge(
    api_key: str,
    business_id: str,
    question: str,
    top_k: int = 8,
) -> dict[str, Any]:
    tenant = _resolve_tenant(api_key)
    biz = _resolve_business(tenant, business_id)
    return {
        "tenant_id": str(tenant.id),
        "business_id": str(biz.id),
        "question": question,
        "top_k": top_k,
        "chunks": [],
        "status": "not_implemented",
        "detail": (
            "query_business_knowledge requires an embedder + populated Qdrant "
            "collection. TEI server isn't running on the shared box yet "
            "(awaiting free GPU). Once it is, this tool returns RetrievedChunks "
            "via bizpulse.retrieval.RetrievalEngine."
        ),
    }


def get_marketing_recommendations(
    api_key: str,
    business_id: str,
    channel: str | None = None,
) -> dict[str, Any]:
    """Phase 6 dependency. Returns a 'pending pipeline' status until Phase 6 lands."""
    tenant = _resolve_tenant(api_key)
    biz = _resolve_business(tenant, business_id)
    return {
        "tenant_id": str(tenant.id),
        "business_id": str(biz.id),
        "channel": channel,
        "recommendations": [],
        "status": "pending_pipeline",
        "detail": "The multi-agent pipeline (Phase 6) is not yet implemented. Run analyze_business() to register a run; once the pipeline lands, recommendations will populate.",
    }
