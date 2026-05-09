"""Playwright crawler — JS-rendered websites + screenshot fallback + same-domain link follow.

Ingestion entry point used by the API/MCP `analyze_business` flow:
  - launches a headless Chromium via Playwright
  - waits for `networkidle` so JS-driven SPAs settle
  - extracts main-content text via trafilatura
  - takes a full-page PNG screenshot to data/screenshots/
  - heuristically classifies the page (pricing / about / blog / case_study / ...)
  - follows same-domain anchor links breadth-first up to `max_pages`,
    deduping by content_hash
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections import deque
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Protocol
from urllib.parse import urljoin, urlparse

from bizpulse.logging import get_logger
from bizpulse.models.common import BusinessId, TenantId
from bizpulse.models.ingest import RawArtifact, SourceType

log = get_logger(__name__)


# ---- protocol -------------------------------------------------------------

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


# ---- url -> source_type heuristics ---------------------------------------

_SOURCE_TYPE_PATTERNS: list[tuple[re.Pattern[str], SourceType]] = [
    (re.compile(r"/pricing(\b|/|$)", re.I), "pricing_page"),
    (re.compile(r"/about(\b|/|$)", re.I), "about_page"),
    (re.compile(r"/(case[\-_]?stud|customer[s]?/)", re.I), "case_study"),
    (re.compile(r"/(testimonial|review)", re.I), "testimonial"),
    (re.compile(r"/blog(\b|/|$)|/(news|insight|article)s?/", re.I), "blog_post"),
]


def classify_url(url: str) -> SourceType:
    path = urlparse(url).path or "/"
    for pat, st in _SOURCE_TYPE_PATTERNS:
        if pat.search(path):
            return st
    return "website_page"


# ---- text extraction ----------------------------------------------------

def extract_text(html: str, url: str) -> str:
    """Extract clean main-content text. Falls back to a minimal HTML strip
    if trafilatura isn't available or returns nothing useful."""
    try:
        import trafilatura  # type: ignore[import-not-found]
        out = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_tables=True,
            no_fallback=False,
        )
        if out and out.strip():
            return out.strip()
    except ImportError:
        pass
    # Fallback: strip tags, collapse whitespace.
    txt = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    txt = re.sub(r"<style.*?</style>", " ", txt, flags=re.S | re.I)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = re.sub(r"\s+", " ", txt)
    return txt.strip()


# ---- crawler ------------------------------------------------------------

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 BizPulseCrawler/1.0"
)


class PlaywrightCrawler:
    """Headless Chromium crawler.

    Construction is cheap; `crawl()` is the real entry point. The browser
    instance is launched per-call and torn down on exit so multiple crawls
    don't share state.
    """

    def __init__(
        self,
        *,
        screenshots_dir: Path | str | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        nav_timeout_ms: int = 30_000,
        request_timeout_ms: int = 60_000,
    ) -> None:
        self.screenshots_dir = (
            Path(screenshots_dir) if screenshots_dir else None
        )
        if self.screenshots_dir:
            self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self.user_agent = user_agent
        self.nav_timeout_ms = nav_timeout_ms
        self.request_timeout_ms = request_timeout_ms

    async def crawl(
        self,
        url: str,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        max_pages: int = 20,
    ) -> AsyncIterator[RawArtifact]:
        # Lazy import so the package import-clean even when playwright isn't
        # installed (e.g. in CI for non-crawler tests).
        from playwright.async_api import async_playwright  # type: ignore[import-not-found]

        domain = urlparse(url).netloc
        if not domain:
            raise ValueError(f"crawl URL must be absolute: {url!r}")

        seen_urls: set[str] = set()
        seen_hashes: set[str] = set()
        queue: deque[str] = deque([url])

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                context = await browser.new_context(user_agent=self.user_agent)
                page = await context.new_page()
                page.set_default_navigation_timeout(self.nav_timeout_ms)
                page.set_default_timeout(self.request_timeout_ms)

                while queue and len(seen_urls) < max_pages:
                    current = queue.popleft()
                    if current in seen_urls:
                        continue
                    seen_urls.add(current)

                    try:
                        artifact, links = await self._fetch_one(
                            page,
                            current,
                            tenant_id=tenant_id,
                            business_id=business_id,
                        )
                    except Exception as exc:  # noqa: BLE001 — Playwright raises lots
                        log.warning("crawler.fetch_failed", url=current, error=str(exc)[:200])
                        continue

                    if artifact.content_hash in seen_hashes:
                        continue
                    seen_hashes.add(artifact.content_hash)
                    yield artifact

                    # Enqueue same-domain in-page links (breadth-first).
                    for href in links:
                        if urlparse(href).netloc == domain and href not in seen_urls:
                            queue.append(href)
            finally:
                await browser.close()

    async def _fetch_one(
        self,
        page,
        url: str,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
    ) -> tuple[RawArtifact, list[str]]:
        """Load one URL and return (artifact, list of same-domain links)."""
        await page.goto(url, wait_until="networkidle")
        html = await page.content()
        title = await page.title()

        text = extract_text(html, url=url)
        if not text:
            text = title or "(no extractable text)"

        screenshot_path: str | None = None
        if self.screenshots_dir:
            content_hash_short = hashlib.sha256(text.encode()).hexdigest()[:16]
            shot = self.screenshots_dir / f"{content_hash_short}.png"
            try:
                await page.screenshot(path=str(shot), full_page=True)
                screenshot_path = str(shot)
            except Exception as exc:  # noqa: BLE001
                log.warning("crawler.screenshot_failed", url=url, error=str(exc)[:200])

        # Pull href attributes from anchors for the queue.
        try:
            link_handles = await page.locator("a[href]").all()
            raw_links = [await h.get_attribute("href") for h in link_handles]
        except Exception:  # noqa: BLE001
            raw_links = []
        abs_links: list[str] = []
        for href in raw_links:
            if not href:
                continue
            absolute = urljoin(url, href)
            # Drop fragments + query params for dedup keying purposes.
            cleaned = absolute.split("#", 1)[0]
            if cleaned.startswith("http"):
                abs_links.append(cleaned)

        artifact = RawArtifact(
            tenant_id=tenant_id,
            business_id=business_id,
            source_url=url,
            source_type=classify_url(url),
            content_hash=RawArtifact.hash_text(text),
            raw_html=html if len(html) < 200_000 else None,
            extracted_text=text,
            screenshot_path=screenshot_path,
        )
        return artifact, abs_links


# ---- test fake (kept here so tests using the orchestrator don't need a real browser)

class FakeCrawler:
    """In-process fake — yields a fixed list of RawArtifacts. Useful for
    end-to-end orchestrator tests without launching a browser."""

    def __init__(self, artifacts: list[RawArtifact]) -> None:
        self._artifacts = artifacts

    async def crawl(
        self,
        url: str,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        max_pages: int = 50,
    ) -> AsyncIterator[RawArtifact]:
        for art in self._artifacts:
            # Reseat tenant/business so callers don't have to pre-stamp them.
            yield art.model_copy(update={"tenant_id": tenant_id, "business_id": business_id})
            await asyncio.sleep(0)
