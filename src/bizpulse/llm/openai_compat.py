"""OpenAI-compatible client.

Used for OpenAI itself, Perplexity, Grok (xAI), and DeepSeek — they all
expose an OpenAI-compatible /v1/chat/completions endpoint, just at a
different base_url.

We use direct httpx instead of the openai SDK so we don't need to juggle
multiple sub-clients (one per base_url). Same logic, less abstraction.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from bizpulse.llm.base import CompletionResult, LLMError, estimate_cost


class OpenAICompatClient:
    """Generic OpenAI-format chat-completions client."""

    def __init__(
        self,
        *,
        vendor: str,
        model: str,
        base_url: str,
        api_key_env: str,
        api_key: str | None = None,
        timeout: float = 60.0,
        max_retries: int = 3,
    ) -> None:
        key = api_key or os.environ.get(api_key_env)
        if not key:
            raise LLMError(
                f"{api_key_env} not set",
                vendor=vendor,
                model=model,
                retryable=False,
            )
        self.vendor = vendor
        self.model = model
        self.name = model
        self.base_url = base_url.rstrip("/")
        self._key = key
        self._timeout = timeout
        self._max_retries = max_retries

    async def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> CompletionResult:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        t0 = time.perf_counter()
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=0.5, max=8.0),
            retry=retry_if_exception_type(
                (httpx.TransportError, httpx.HTTPStatusError, _Retryable)
            ),
            reraise=True,
        ):
            with attempt:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    r = await client.post(url, headers=headers, json=payload)
                if r.status_code == 429 or 500 <= r.status_code < 600:
                    raise _Retryable(f"{self.vendor} {r.status_code}: {r.text[:200]}")
                if r.status_code >= 400:
                    raise LLMError(
                        f"{self.vendor} {r.status_code}: {r.text[:300]}",
                        vendor=self.vendor,
                        model=self.model,
                        retryable=False,
                    )
                data = r.json()
                break
        else:  # pragma: no cover
            raise LLMError(
                f"{self.vendor} retries exhausted",
                vendor=self.vendor,
                model=self.model,
                retryable=True,
            )

        latency_ms = (time.perf_counter() - t0) * 1000.0
        try:
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            in_tok = int(usage.get("prompt_tokens", 0))
            out_tok = int(usage.get("completion_tokens", 0))
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(
                f"{self.vendor} returned unparseable response: {exc}; raw={str(data)[:300]}",
                vendor=self.vendor,
                model=self.model,
                retryable=False,
            ) from exc

        return CompletionResult(
            text=text,
            model=self.model,
            vendor=self.vendor,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=estimate_cost(self.vendor, self.model, in_tok, out_tok),
            latency_ms=latency_ms,
            raw={"id": data.get("id"), "finish_reason": data["choices"][0].get("finish_reason")},
        )


class _Retryable(Exception):
    """Internal sentinel for tenacity to retry transient failures."""


# ---- vendor-specific factories ------------------------------------------


def openai_client(model: str = "gpt-4o", **kw: Any) -> OpenAICompatClient:
    return OpenAICompatClient(
        vendor="openai",
        model=model,
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        **kw,
    )


def perplexity_client(model: str = "sonar-pro", **kw: Any) -> OpenAICompatClient:
    """Perplexity has built-in web search — best for the Competitor Scout role."""
    return OpenAICompatClient(
        vendor="perplexity",
        model=model,
        base_url="https://api.perplexity.ai",
        api_key_env="PERPLEXITY_API_KEY",
        **kw,
    )


def grok_client(model: str = "grok-4", **kw: Any) -> OpenAICompatClient:
    """xAI Grok — adds X/Twitter context. Default model 'grok-4'."""
    return OpenAICompatClient(
        vendor="xai",
        model=model,
        base_url="https://api.x.ai/v1",
        api_key_env="XAI_API_KEY",
        **kw,
    )


def deepseek_client(model: str = "deepseek-chat", **kw: Any) -> OpenAICompatClient:
    """DeepSeek — cheap and strong on reasoning. Use 'deepseek-reasoner' for chain-of-thought."""
    return OpenAICompatClient(
        vendor="deepseek",
        model=model,
        base_url="https://api.deepseek.com",
        api_key_env="DEEPSEEK_API_KEY",
        **kw,
    )


def groq_client(model: str = "llama-3.3-70b-versatile", **kw: Any) -> OpenAICompatClient:
    """Groq — open-source models (Llama 3.3, Mixtral, Gemma 2) on LPU hardware.

    NOT xAI's Grok (see GrokClient for that). Groq is the fast-inference
    platform; latency is typically <2s for full responses, which makes it
    a strong Council member for keeping debate rounds snappy.
    """
    return OpenAICompatClient(
        vendor="groq",
        model=model,
        base_url="https://api.groq.com/openai/v1",
        api_key_env="GROQ_API_KEY",
        **kw,
    )


def openrouter_client(
    model: str = "anthropic/claude-sonnet-4-6",
    **kw: Any,
) -> OpenAICompatClient:
    """OpenRouter — single gateway, hundreds of upstream models.

    Models are addressed as 'provider/name', e.g.
    'anthropic/claude-sonnet-4-6', 'openai/gpt-4o', 'meta-llama/llama-3.3-70b-instruct'.
    Cost is reported in OpenRouter's response usage but our estimate_cost
    table doesn't carry per-route pricing — it returns 0 for openrouter,
    so use OpenRouter's dashboard for billing truth.
    """
    return OpenAICompatClient(
        vendor="openrouter",
        model=model,
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        **kw,
    )


def mistral_client(model: str = "mistral-small-latest", **kw: Any) -> OpenAICompatClient:
    """Mistral — European-built foundation models (mistral-large/medium/small,
    ministral-8b/3b, codestral). OpenAI-compatible /v1/chat/completions.

    Default 'mistral-small-latest' is the price/quality sweet spot for
    Council membership; bump to 'mistral-large-latest' for the judge role
    if you want stronger synthesis."""
    return OpenAICompatClient(
        vendor="mistral",
        model=model,
        base_url="https://api.mistral.ai/v1",
        api_key_env="MISTRAL_API_KEY",
        **kw,
    )
