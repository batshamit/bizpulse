"""Tests for the TEI embed/rerank clients (mocked HTTP)."""

from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from bizpulse.retrieval import TEIEmbedder, TEIError, TEIReranker


@pytest.mark.asyncio
async def test_embed_batch_roundtrip(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="http://test.local/embed",
        method="POST",
        json=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
    )
    async with TEIEmbedder(base_url="http://test.local") as embed:
        out = await embed.embed(["a", "b"])
    assert out == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]


@pytest.mark.asyncio
async def test_embed_4xx_fails_fast(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="http://test.local/embed",
        method="POST",
        status_code=422,
        text="bad input",
    )
    async with TEIEmbedder(base_url="http://test.local", max_retries=3) as embed:
        with pytest.raises(TEIError, match="422"):
            await embed.embed(["a"])


@pytest.mark.asyncio
async def test_rerank_returns_sorted_pairs(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="http://test.local/rerank",
        method="POST",
        json=[
            {"index": 2, "score": 0.91},
            {"index": 0, "score": 0.42},
            {"index": 1, "score": 0.05},
        ],
    )
    async with TEIReranker(base_url="http://test.local") as rerank:
        pairs = await rerank.rerank("question", ["a", "b", "c"])
    assert pairs == [(2, 0.91), (0, 0.42), (1, 0.05)]


@pytest.mark.asyncio
async def test_empty_input_short_circuits(httpx_mock: HTTPXMock) -> None:
    # No HTTP calls should be made.
    async with TEIEmbedder(base_url="http://test.local") as embed:
        assert await embed.embed([]) == []
    async with TEIReranker(base_url="http://test.local") as rr:
        assert await rr.rerank("q", []) == []
