"""BizPulse MCP server — registers our tools on a FastMCP instance.

Run via `python -m bizpulse.mcp` or `bizpulse mcp serve`. Default transport is
stdio, which is what Claude Desktop / Cursor expect. SSE transport is a flag
flip if needed for HTTP-style clients.

Why MCP? The plan section 5: BizPulse exposes its capabilities via MCP so any
MCP-compatible client (Claude Desktop, Cursor, customer agents) can drive the
pipeline through a uniform tool surface. Internal agent-to-agent
communication is done in LangGraph, NOT MCP — MCP lives at the SYSTEM
boundary.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from bizpulse import __version__
from bizpulse.mcp import tools as _t

mcp = FastMCP(
    name="bizpulse",
    instructions=(
        "BizPulse — multi-agent RAG marketing-strategy platform. "
        "Use register_tenant first to obtain an api_key, then register_business, "
        "then analyze_business. Use query_business_knowledge for grounded RAG "
        "queries against a tenant's knowledge base."
    ),
)


# Decorate each tool. Keeping the signatures explicit (rather than **kwargs)
# so MCP clients see proper type hints in their tool catalog.


@mcp.tool()
def register_tenant(name: str, slug: str | None = None) -> dict[str, Any]:
    """Create a new BizPulse tenant. Returns the api_key (shown once)."""
    return _t.register_tenant(name=name, slug=slug)


@mcp.tool()
def whoami(api_key: str) -> dict[str, Any]:
    """Return the tenant bound to an api_key."""
    return _t.whoami(api_key=api_key)


@mcp.tool()
def list_industries() -> list[str]:
    """Names of supported industry verticals."""
    return _t.list_industries()


@mcp.tool()
def get_industry_pack(slug: str) -> dict[str, Any]:
    """Full IndustryPack for one slug (ontology, regulations, competitor seeds, channel weights, content pillars, prompt addendum)."""
    return _t.get_industry_pack(slug=slug)


@mcp.tool()
def register_business(api_key: str, url: str, industry: str | None = None) -> dict[str, Any]:
    """Register a business under your tenant. industry is optional but recommended."""
    return _t.register_business(api_key=api_key, url=url, industry=industry)


@mcp.tool()
def list_businesses(api_key: str) -> list[dict[str, Any]]:
    """List businesses registered under your tenant."""
    return _t.list_businesses(api_key=api_key)


@mcp.tool()
async def analyze_business(
    api_key: str, business_id: str, num_llms: int | None = None
) -> dict[str, Any]:
    """Kick off the multi-agent pipeline for a business; returns a pending RunRecord."""
    return await _t.analyze_business(api_key=api_key, business_id=business_id, num_llms=num_llms)


@mcp.tool()
def get_run(api_key: str, run_id: str) -> dict[str, Any]:
    """Fetch a RunRecord by id (cross-tenant lookups return not-found)."""
    return _t.get_run(api_key=api_key, run_id=run_id)


@mcp.tool()
def list_runs_for_business(api_key: str, business_id: str) -> list[dict[str, Any]]:
    """List all runs for a business under your tenant."""
    return _t.list_runs_for_business(api_key=api_key, business_id=business_id)


@mcp.tool()
async def query_business_knowledge(
    api_key: str,
    business_id: str,
    question: str,
    top_k: int = 8,
) -> dict[str, Any]:
    """Hybrid-search a business's vector store."""
    return await _t.query_business_knowledge(
        api_key=api_key,
        business_id=business_id,
        question=question,
        top_k=top_k,
    )


@mcp.tool()
async def get_marketing_recommendations(
    api_key: str,
    business_id: str,
    channel: str | None = None,
) -> dict[str, Any]:
    """Channel-scoped marketing recommendations."""
    return await _t.get_marketing_recommendations(
        api_key=api_key,
        business_id=business_id,
        channel=channel,
    )


def main() -> None:
    """Entrypoint for `python -m bizpulse.mcp`."""
    mcp.run()


__all__ = ["__version__", "main", "mcp"]
