"""Tests for the vendor adapters using mocked HTTP / mocked SDK.

Live tests against real APIs are gated by the presence of the relevant env
var (skipped otherwise) — those run in CI when secrets are available.
"""

from __future__ import annotations

import os
import re

import pytest
from pytest_httpx import HTTPXMock

from bizpulse.llm import LLMError
from bizpulse.llm.gemini_client import GeminiClient
from bizpulse.llm.openai_compat import (
    deepseek_client,
    grok_client,
    openai_client,
    perplexity_client,
)

# --- mocked OpenAI-compat ----------------------------------------------------


@pytest.mark.asyncio
async def test_openai_compat_happy_path(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://api.openai.com/v1/chat/completions",
        json={
            "id": "resp-1",
            "choices": [
                {
                    "message": {"role": "assistant", "content": "hello world"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3},
        },
    )
    c = openai_client(api_key="sk-fake", model="gpt-4o")
    out = await c.complete(system="sys", user="u")
    assert out.text == "hello world"
    assert out.input_tokens == 12 and out.output_tokens == 3
    assert out.vendor == "openai"
    assert out.cost_usd > 0


@pytest.mark.asyncio
async def test_openai_compat_4xx_raises(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://api.openai.com/v1/chat/completions",
        status_code=400,
        text="bad request",
    )
    c = openai_client(api_key="sk-fake")
    with pytest.raises(LLMError, match="400"):
        await c.complete("sys", "u")


@pytest.mark.asyncio
async def test_openai_compat_5xx_retried(httpx_mock: HTTPXMock) -> None:
    """500 should be retried; we send two 500s then a 200."""
    for _ in range(2):
        httpx_mock.add_response(
            url="https://api.openai.com/v1/chat/completions",
            status_code=500,
            text="oops",
        )
    httpx_mock.add_response(
        url="https://api.openai.com/v1/chat/completions",
        json={
            "choices": [{"message": {"content": "recovered"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2},
        },
    )
    c = openai_client(api_key="sk-fake", max_retries=4)
    out = await c.complete("sys", "u")
    assert out.text == "recovered"


@pytest.mark.asyncio
async def test_perplexity_uses_correct_url(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://api.perplexity.ai/chat/completions",
        json={
            "choices": [{"message": {"content": "from perplexity"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
    )
    c = perplexity_client(api_key="pplx-fake")
    out = await c.complete("sys", "u")
    assert out.text == "from perplexity"
    assert out.vendor == "perplexity"


@pytest.mark.asyncio
async def test_grok_and_deepseek_use_their_urls(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://api.x.ai/v1/chat/completions",
        json={
            "choices": [{"message": {"content": "grok!"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
    )
    httpx_mock.add_response(
        url="https://api.deepseek.com/chat/completions",
        json={
            "choices": [{"message": {"content": "deepseek!"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
    )
    g = grok_client(api_key="xai-fake")
    d = deepseek_client(api_key="ds-fake")
    assert (await g.complete("s", "u")).text == "grok!"
    assert (await d.complete("s", "u")).text == "deepseek!"


# --- mocked Gemini ----------------------------------------------------------


@pytest.mark.asyncio
async def test_gemini_happy_path(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=re.compile(
            r"https://generativelanguage\.googleapis\.com/v1beta/models/gemini-2\.5-pro:generateContent\?key=.*"
        ),
        json={
            "candidates": [
                {
                    "content": {"parts": [{"text": "hello from gemini"}]},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 4},
        },
    )
    c = GeminiClient(api_key="AIza-fake")
    out = await c.complete("sys", "u")
    assert out.text == "hello from gemini"
    assert out.vendor == "google"
    assert out.input_tokens == 7
    assert out.output_tokens == 4


@pytest.mark.asyncio
async def test_gemini_missing_key_raises() -> None:
    """No key in env or arg = LLMError at construction time, not at call time."""
    saved = (os.environ.pop("GOOGLE_API_KEY", None), os.environ.pop("GEMINI_API_KEY", None))
    try:
        with pytest.raises(LLMError, match="GOOGLE_API_KEY"):
            GeminiClient()
    finally:
        if saved[0] is not None:
            os.environ["GOOGLE_API_KEY"] = saved[0]
        if saved[1] is not None:
            os.environ["GEMINI_API_KEY"] = saved[1]


# --- factory --------------------------------------------------------------


def test_factory_available_vendors_reflects_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from bizpulse.llm.factory import available_vendors

    # Clear all
    for var in (
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "PERPLEXITY_API_KEY",
        "XAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "GROQ_API_KEY",
        "MISTRAL_API_KEY",
        "OPENROUTER_API_KEY",
        "OLLAMA_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9999/v1")
    assert available_vendors() == []

    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-fake")
    avail = set(available_vendors())
    assert "openai" in avail and "deepseek" in avail


def test_factory_build_council_raises_with_no_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    from bizpulse.llm.factory import build_council

    for var in (
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "PERPLEXITY_API_KEY",
        "XAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "GROQ_API_KEY",
        "MISTRAL_API_KEY",
        "OPENROUTER_API_KEY",
        "OLLAMA_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9999/v1")
    with pytest.raises(RuntimeError, match="No LLM API keys"):
        build_council()
