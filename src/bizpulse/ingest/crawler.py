"""Playwright crawler — Phase 3 stub, real implementation lands later.

Defines the contract; the real Playwright wiring is deferred until Phase 6/9
when we have real businesses to crawl and a free GPU to embed them. The stub
is callable by tests so the orchestrator wiring can be validated end-to-end
against a `FakeCrawler`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from bizpulse.models.common import BusinessId, TenantId
from bizpulse.models.ingest import RawArtifact


class CrawlerProtocol(Protocol):
    async def crawl(
        self,
        url: str,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        max_pages: int = 50,
    ) -> AsyncIterator[RawArtifact]:  # pragma: no cover - protocol
        ...


class PlaywrightCrawler:
    """Real Playwright crawler — NOT yet implemented.

    When this lands it will:
      - launch a headless chromium browser
      - load the URL with networkidle wait
      - take a full-page screenshot to ./data/screenshots/<hash>.png
      - extract main-content text via trafilatura
      - emit RawArtifact for the landing page
      - follow same-domain anchor links up to `max_pages`, deduping by content_hash
      - emit one RawArtifact per page
      - source_type heuristic: /pricing → pricing_page; /about → about_page;
        /blog/* → blog_post; /case-stud* → case_study; testimonial-y URL → testimonial
    """

    async def crawl(
        self,
        url: str,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        max_pages: int = 50,
    ) -> AsyncIterator[RawArtifact]:
        raise NotImplementedError(
            "PlaywrightCrawler is a Phase-3 stub. "
            "Use FakeCrawler in tests; real implementation lands in a later phase."
        )
        # The unreachable yield below makes mypy happy that this is an async generator.
        yield  # type: ignore[unreachable]
