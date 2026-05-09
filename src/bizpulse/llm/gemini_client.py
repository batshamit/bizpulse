"""Google Gemini client.

Uses the AI Studio / Generative Language REST API directly via httpx —
avoids pulling in the heavy `google-genai` SDK. The API surface is small
enough that direct HTTP is cleaner.

Endpoint:
  POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key=KEY
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


class GeminiClient:
    """Async client for Google AI Studio's Gemini REST API."""

    vendor = "google"

    def __init__(
        self,
        model: str = "gemini-2.5-pro",
        api_key: str | None = None,
        timeout: float = 60.0,
        max_retries: int = 3,
    ) -> None:
        key = api_key or os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise LLMError(
                "GOOGLE_API_KEY (or GEMINI_API_KEY) not set",
                vendor=self.vendor,
                model=model,
                retryable=False,
            )
        self.name = model
        self.model = model
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
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/"
            f"models/{self.model}:generateContent?key={self._key}"
        )
        payload: dict[str, Any] = {
            "systemInstruction": {"role": "system", "parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }

        t0 = time.perf_counter()
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=0.5, max=8.0),
            retry=retry_if_exception_type((httpx.TransportError, _GeminiRetryable)),
            reraise=True,
        ):
            with attempt:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    r = await client.post(url, json=payload)
                if r.status_code == 429 or 500 <= r.status_code < 600:
                    raise _GeminiRetryable(f"gemini {r.status_code}: {r.text[:200]}")
                if r.status_code >= 400:
                    raise LLMError(
                        f"gemini {r.status_code}: {r.text[:300]}",
                        vendor=self.vendor,
                        model=self.model,
                        retryable=False,
                    )
                data = r.json()
                break
        else:  # pragma: no cover
            raise LLMError(
                "gemini retries exhausted",
                vendor=self.vendor,
                model=self.model,
                retryable=True,
            )

        latency_ms = (time.perf_counter() - t0) * 1000.0
        try:
            text_parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in text_parts)
            usage = data.get("usageMetadata", {})
            in_tok = int(usage.get("promptTokenCount", 0))
            out_tok = int(usage.get("candidatesTokenCount", 0))
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(
                f"gemini returned unparseable response: {exc}; raw={str(data)[:300]}",
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
            raw={"finish_reason": data["candidates"][0].get("finishReason")},
        )


class _GeminiRetryable(Exception):
    """Internal sentinel for tenacity to retry transient failures."""
