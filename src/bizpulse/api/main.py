"""FastAPI app — BizPulse public HTTP surface.

The actual multi-agent pipeline lives in `bizpulse.agents` (Phase 6+).
Endpoints here are the contract every caller (web UI, MCP, CLI) goes through.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from bizpulse import __version__
from bizpulse.api.businesses import router as businesses_router
from bizpulse.api.runs import router as runs_router
from bizpulse.api.tenants import router as tenants_router
from bizpulse.config import settings
from bizpulse.logging import configure, get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure(settings.log_level)
    log.info("bizpulse.api.start", version=__version__, env=settings.env)
    yield
    log.info("bizpulse.api.stop")


app = FastAPI(
    title="BizPulse",
    version=__version__,
    description="Multi-agent RAG platform for grounded marketing strategy.",
    lifespan=lifespan,
)

app.include_router(tenants_router)
app.include_router(businesses_router)
app.include_router(runs_router)


@app.get("/healthz", tags=["meta"])
async def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    return {
        "service": "bizpulse",
        "version": __version__,
        "docs": "/docs",
        "health": "/healthz",
    }
