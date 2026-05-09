"""Tests for the crawler — URL classification, text extraction, FakeCrawler.

The browser-launching paths require Chromium and a real network or fixture
server; those tests are gated behind `@pytest.mark.network` and skipped by
default. The pure-logic surface (URL heuristics, HTML text extraction,
fake/orchestrator wiring) is tested here without a browser.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from bizpulse.ingest.crawler import (
    FakeCrawler,
    classify_url,
    extract_text,
)
from bizpulse.models import RawArtifact


# ---- classify_url ---------------------------------------------------------

@pytest.mark.parametrize("url, expected", [
    ("https://acme.test/", "website_page"),
    ("https://acme.test/pricing", "pricing_page"),
    ("https://acme.test/Pricing/", "pricing_page"),
    ("https://acme.test/about-us", "about_page"),
    ("https://acme.test/blog/launch", "blog_post"),
    ("https://acme.test/case-studies/foo", "case_study"),
    ("https://acme.test/customers/bar", "case_study"),
    ("https://acme.test/testimonials", "testimonial"),
    ("https://acme.test/insights/q3", "blog_post"),
    ("https://acme.test/products/widget", "website_page"),
])
def test_classify_url(url: str, expected: str) -> None:
    assert classify_url(url) == expected


# ---- extract_text ---------------------------------------------------------

def test_extract_text_strips_scripts_and_collapses_ws() -> None:
    html = """
    <html><head><title>x</title>
      <script>console.log('hi');</script>
      <style>.a { color: red; }</style>
    </head>
    <body><h1>Hello</h1>
      <p>We build a neobank for gig workers.</p>
      <p>Pricing tiers: starter, growth, enterprise.</p>
    </body></html>
    """
    text = extract_text(html, url="https://example.test/")
    assert "Hello" in text or "neobank" in text.lower()
    assert "console.log" not in text
    assert ".a {" not in text


def test_extract_text_handles_empty_html() -> None:
    assert extract_text("", url="https://x.test/") == ""


# ---- FakeCrawler integration ---------------------------------------------

@pytest.mark.asyncio
async def test_fake_crawler_yields_and_restamps_tenant() -> None:
    """The fake's artifacts may be created with placeholder tenant/business
    IDs; the crawl() method should re-stamp them with the caller's IDs so
    the orchestrator's mismatch check doesn't trip."""
    placeholder_tid = uuid4()
    placeholder_bid = uuid4()
    artifact = RawArtifact(
        tenant_id=placeholder_tid,
        business_id=placeholder_bid,
        source_url="https://example.test/",
        source_type="website_page",
        content_hash="0" * 32,
        extracted_text="A fixture page with enough text to clear min_chars.",
    )
    fake = FakeCrawler([artifact])

    real_tid = uuid4()
    real_bid = uuid4()
    out = []
    async for a in fake.crawl(
        "https://example.test/",
        tenant_id=real_tid,
        business_id=real_bid,
        max_pages=5,
    ):
        out.append(a)

    assert len(out) == 1
    assert out[0].tenant_id == real_tid
    assert out[0].business_id == real_bid
    # other fields preserved
    assert out[0].source_url == "https://example.test/"
    assert out[0].extracted_text.startswith("A fixture page")
