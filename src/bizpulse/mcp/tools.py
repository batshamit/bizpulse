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

import asyncio
from typing import Any
from uuid import UUID

from bizpulse.models import (
    SUPPORTED_INDUSTRIES,
    Business,
    Tenant,
    load_all_industries,
    load_industry,
)
from bizpulse.storage import Store, get_default_store

_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


class AuthError(RuntimeError):
    """Bad / missing api_key."""


class NotFoundError(RuntimeError):
    """Resource doesn't exist or doesn't belong to the caller's tenant."""


# --- helpers ------------------------------------------------------------


def _store() -> Store:
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


def register_tenant(name: str, slug: str | None = None) -> dict[str, Any]:
    """Create a new tenant. Returns the api_key (only shown once)."""
    tenant = _store().create_tenant(name=name, slug=slug)
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


async def analyze_business(
    api_key: str,
    business_id: str,
    num_llms: int | None = None,
) -> dict[str, Any]:
    """Kick off the multi-agent pipeline for a business. Returns a RunRecord
    in `pending` state and schedules the background analysis task.
    """
    tenant = _resolve_tenant(api_key)
    biz = _resolve_business(tenant, business_id)
    run = _store().create_run(tenant.id, biz.id)
    from bizpulse.api.runner_service import run_analysis_background

    task = asyncio.create_task(
        run_analysis_background(
            run_id=run.id,
            business=biz,
            num_llms=num_llms,
        )
    )
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
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


async def query_business_knowledge(
    api_key: str,
    business_id: str,
    question: str,
    top_k: int = 8,
) -> dict[str, Any]:
    """Query the business's vector knowledge base from the latest completed run."""
    tenant = _resolve_tenant(api_key)
    biz = _resolve_business(tenant, business_id)

    runs = _store().list_runs_for_business(biz.id)
    completed_runs = [r for r in runs if r.status == "complete"]
    if not completed_runs:
        return {
            "tenant_id": str(tenant.id),
            "business_id": str(biz.id),
            "question": question,
            "top_k": top_k,
            "chunks": [],
            "status": "pending_pipeline",
            "detail": "No completed runs found for this business. Run analyze_business first.",
        }
    latest_run = max(completed_runs, key=lambda r: r.finished_at or r.started_at)
    run_id = latest_run.id

    from qdrant_client import QdrantClient

    from bizpulse.api.runner_service import _QDRANT_BASE, _pick_embedder
    from bizpulse.models.retrieval import RetrievalQuery
    from bizpulse.retrieval import RetrievalEngine, TenantQdrant

    embedder = _pick_embedder()
    qd_dir = _QDRANT_BASE / f"run-{run_id}"
    repo = TenantQdrant(tenant.id, client=QdrantClient(path=str(qd_dir)))
    retriever = RetrievalEngine(repo, embedder=embedder)

    query = RetrievalQuery(
        text=question,
        tenant_id=tenant.id,
        business_id=biz.id,
        industry=biz.industry,
        top_k=top_k,
    )
    res = await retriever.search(query)

    return {
        "tenant_id": str(tenant.id),
        "business_id": str(biz.id),
        "question": question,
        "top_k": top_k,
        "chunks": [c.model_dump(mode="json") for c in res.chunks],
        "status": "complete",
        "detail": "Retrieved chunks from the active run vector database.",
    }


async def get_marketing_recommendations(
    api_key: str,
    business_id: str,
    channel: str | None = None,
) -> dict[str, Any]:
    """Retrieve marketing recommendations from the latest completed run."""
    tenant = _resolve_tenant(api_key)
    biz = _resolve_business(tenant, business_id)

    runs = _store().list_runs_for_business(biz.id)
    completed_runs = [
        r for r in runs
        if r.status == "complete" and r.final_output is not None and r.run_type == "marketing_strategy"
    ]
    if not completed_runs:
        return {
            "tenant_id": str(tenant.id),
            "business_id": str(biz.id),
            "channel": channel,
            "recommendations": [],
            "status": "pending_pipeline",
            "detail": "No completed runs with final output found for this business.",
        }
    latest_run = max(completed_runs, key=lambda r: r.finished_at or r.started_at)
    strategy = latest_run.final_output
    from bizpulse.models import MarketingStrategy

    assert isinstance(strategy, MarketingStrategy)
    recs = strategy.recommendations
    if channel:
        recs = [r for r in recs if r.channel == channel]

    return {
        "tenant_id": str(tenant.id),
        "business_id": str(biz.id),
        "channel": channel,
        "recommendations": [r.model_dump(mode="json") for r in recs],
        "status": "complete",
        "detail": f"Loaded recommendations from run {latest_run.id}.",
    }
