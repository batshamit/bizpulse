"""In-process fakes for tests and dry-runs.

`FakeLLMClient` returns canned responses (or a callable's output). It records
every call so tests can assert on prompts/order. No network, no async sleeps.

Use `ScriptedLLMClient` when you need different responses per round of a
Council debate.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from bizpulse.llm.base import CompletionResult, LLMError


@dataclass
class _Call:
    system: str
    user: str
    max_tokens: int
    temperature: float


class FakeLLMClient:
    """Returns the same canned text for every call."""

    def __init__(
        self,
        name: str = "fake",
        vendor: str = "fake",
        response: str = "{}",
        latency_ms: float = 1.0,
        cost_usd: float = 0.0001,
        raise_on_call: Exception | None = None,
    ) -> None:
        self.name = name
        self.vendor = vendor
        self._response = response
        self._latency_ms = latency_ms
        self._cost_usd = cost_usd
        self._raise = raise_on_call
        self.calls: list[_Call] = []

    async def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> CompletionResult:
        self.calls.append(
            _Call(system=system, user=user, max_tokens=max_tokens, temperature=temperature)
        )
        if self._raise is not None:
            raise self._raise
        return CompletionResult(
            text=self._response,
            model=self.name,
            vendor=self.vendor,
            input_tokens=len((system + user).split()),
            output_tokens=len(self._response.split()),
            cost_usd=self._cost_usd,
            latency_ms=self._latency_ms,
            raw={},
        )


class ScriptedLLMClient:
    """Returns one response per call, in order. Useful for multi-round Council
    tests where each round expects a different proposal/revision.
    """

    def __init__(
        self,
        name: str,
        vendor: str,
        responses: list[str],
        *,
        cost_usd: float = 0.0001,
        latency_ms: float = 1.0,
    ) -> None:
        self.name = name
        self.vendor = vendor
        self._responses = list(responses)
        self._index = 0
        self._cost_usd = cost_usd
        self._latency_ms = latency_ms
        self.calls: list[_Call] = []

    async def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> CompletionResult:
        self.calls.append(
            _Call(system=system, user=user, max_tokens=max_tokens, temperature=temperature)
        )
        if self._index >= len(self._responses):
            raise LLMError(
                f"ScriptedLLMClient {self.name!r} ran out of scripted responses "
                f"(scripted {len(self._responses)}, asked {self._index + 1})",
                vendor=self.vendor,
                model=self.name,
                retryable=False,
            )
        text = self._responses[self._index]
        self._index += 1
        return CompletionResult(
            text=text,
            model=self.name,
            vendor=self.vendor,
            input_tokens=len((system + user).split()),
            output_tokens=len(text.split()),
            cost_usd=self._cost_usd,
            latency_ms=self._latency_ms,
            raw={},
        )


class CallableLLMClient:
    """Takes a (system, user) -> str function. Most flexible fake."""

    def __init__(
        self,
        name: str,
        vendor: str,
        fn: Callable[[str, str], str],
        *,
        cost_usd: float = 0.0001,
        latency_ms: float = 1.0,
    ) -> None:
        self.name = name
        self.vendor = vendor
        self._fn = fn
        self._cost_usd = cost_usd
        self._latency_ms = latency_ms

    async def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> CompletionResult:
        text = self._fn(system, user)
        return CompletionResult(
            text=text,
            model=self.name,
            vendor=self.vendor,
            input_tokens=len((system + user).split()),
            output_tokens=len(text.split()),
            cost_usd=self._cost_usd,
            latency_ms=self._latency_ms,
            raw={},
        )
