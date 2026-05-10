"""FastAPI app — BizPulse public HTTP surface.

The actual multi-agent pipeline lives in `bizpulse.agents` (Phase 6+).
Endpoints here are the contract every caller (web UI, MCP, CLI) goes through.

`/ui/*` is the static GUI (Anthropic-aesthetic SPA via Tailwind+Alpine, no
build step). `/` redirects to it; the JSON service info moves to `/api`.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from bizpulse import __version__
from bizpulse.api.businesses import router as businesses_router
from bizpulse.api.runs import router as runs_router
from bizpulse.api.tenants import router as tenants_router
from bizpulse.config import settings
from bizpulse.logging import configure, get_logger

log = get_logger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"


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

# Static GUI mounted at /ui (html=True serves index.html on /ui/).
if STATIC_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=str(STATIC_DIR), html=True), name="ui")


@app.get("/healthz", tags=["meta"])
async def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/api", tags=["meta"])
async def api_root() -> dict[str, str]:
    return {
        "service": "bizpulse",
        "version": __version__,
        "docs": "/docs",
        "ui": "/ui/",
        "health": "/healthz",
    }


@app.get("/", include_in_schema=False)
async def root_redirect():
    """Redirect the root to the GUI."""
    return RedirectResponse(url="/ui/")
