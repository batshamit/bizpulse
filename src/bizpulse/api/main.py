"""FastAPI app — Phase 1 scaffold. Real endpoints land in Phase 9."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from bizpulse import __version__
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


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "service": "bizpulse",
        "version": __version__,
        "docs": "/docs",
        "health": "/healthz",
    }
