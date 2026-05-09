"""Anthropic / Claude client adapter."""

from __future__ import annotations

import os
import time
from typing import Any

from bizpulse.llm.base import (
    PRICING_PER_1K,
    CompletionResult,
    LLMError,
    estimate_cost,
)
from bizpulse.logging import get_logger

log = get_logger(__name__)


class AnthropicClient:
    """Async wrapper over the official `anthropic` SDK."""

    vendor = "anthropic"

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        api_key: str | None = None,
        timeout: float = 60.0,
        max_retries: int = 2,
    ) -> None:
        # Lazy import so the package import doesn't fail when the SDK isn't installed.
        try:
            from anthropic import AsyncAnthropic  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - environment issue
            raise LLMError(
                "anthropic SDK not installed; pip install anthropic",
                vendor=self.vendor,
                model=model,
                retryable=False,
            ) from exc

        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise LLMError(
                "ANTHROPIC_API_KEY not set",
                vendor=self.vendor,
                model=model,
                retryable=False,
            )

        self.name = model
        self.model = model
        self._client = AsyncAnthropic(api_key=key, timeout=timeout, max_retries=max_retries)

    async def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> CompletionResult:
        t0 = time.perf_counter()
        try:
            resp = await self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except Exception as exc:  # noqa: BLE001 — anthropic raises hierarchy of types
            retryable = "rate" in str(exc).lower() or "overloaded" in str(exc).lower()
            raise LLMError(
                f"anthropic call failed: {exc}",
                vendor=self.vendor,
                model=self.model,
                retryable=retryable,
            ) from exc

        latency_ms = (time.perf_counter() - t0) * 1000.0
        # Concatenate text blocks (Claude can return multiple).
        text = "".join(getattr(b, "text", "") for b in resp.content)
        in_tok = int(getattr(resp.usage, "input_tokens", 0))
        out_tok = int(getattr(resp.usage, "output_tokens", 0))
        cost = estimate_cost(self.vendor, self.model, in_tok, out_tok)

        return CompletionResult(
            text=text,
            model=self.model,
            vendor=self.vendor,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=cost,
            latency_ms=latency_ms,
            raw={"id": getattr(resp, "id", None), "stop_reason": getattr(resp, "stop_reason", None)},
        )
