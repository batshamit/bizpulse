"""LLM client Protocol — every vendor implements this.

Why a Protocol rather than ABC: lets us drop in mocks (e.g., FakeLLMClient in
tests) without inheritance gymnastics, and lets vendor SDKs that ship their
own client classes adapt via thin wrappers.

Cost is tracked per-call so the Council can report total spend per BizPulse
run — useful both for cost guardrails and for the demo ("this analysis cost
$0.43").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from bizpulse.models.common import utcnow


@dataclass(frozen=True)
class CompletionResult:
    """One LLM call's output + bookkeeping."""

    text: str
    model: str
    vendor: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float
    finished_at: datetime = field(default_factory=utcnow)
    raw: dict[str, object] = field(default_factory=dict)
    """Vendor-specific extras (refusal flags, tool calls, etc.)."""


@runtime_checkable
class LLMClient(Protocol):
    """Anything that turns (system, user) into one CompletionResult."""

    name: str
    """Human/log-friendly identifier — e.g., 'claude-opus-4-5', 'gpt-4o'."""

    vendor: str
    """Coarse vendor name — 'anthropic', 'openai', 'google', 'perplexity', ..."""

    async def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> CompletionResult:  # pragma: no cover - protocol stub
        ...


class LLMError(RuntimeError):
    """Vendor-side failure (auth, rate limit, content-filter refusal, 5xx)."""

    def __init__(self, message: str, *, vendor: str, model: str, retryable: bool) -> None:
        super().__init__(message)
        self.vendor = vendor
        self.model = model
        self.retryable = retryable


# ----- pricing helpers (rough as of mid-2026; tune in vendor clients) ------
# Used by the test fakes and as defaults; real vendors override per-call from
# response usage fields.

PRICING_PER_1K = {
    # vendor:model -> (input_$/1k, output_$/1k)
    "anthropic:claude-opus-4-5":    (0.015, 0.075),
    "anthropic:claude-sonnet-4-5":  (0.003, 0.015),
    "anthropic:claude-haiku-4-5":   (0.001, 0.005),
    "openai:gpt-4o":                (0.0025, 0.010),
    "openai:gpt-4o-mini":           (0.00015, 0.00060),
    "openai:o1":                    (0.015, 0.060),
    "google:gemini-2.5-pro":        (0.00125, 0.005),
    "google:gemini-2.5-flash":      (0.0001, 0.00040),
    "google:gemini-2.0-flash":      (0.0001, 0.00040),
    "perplexity:sonar-pro":         (0.003, 0.015),
    "perplexity:sonar-reasoning":   (0.001, 0.005),
    "xai:grok-4":                   (0.005, 0.025),
    "xai:grok-2":                   (0.002, 0.010),
    "deepseek:deepseek-chat":       (0.00027, 0.0011),
    "deepseek:deepseek-reasoner":   (0.00055, 0.00219),
    # Groq — Llama 3.3 / Mixtral / Gemma on LPU hardware. Cheap & fast.
    "groq:llama-3.3-70b-versatile": (0.00059, 0.00079),
    "groq:llama-3.1-8b-instant":    (0.00005, 0.00008),
    "groq:mixtral-8x7b-32768":      (0.00024, 0.00024),
    "groq:gemma2-9b-it":            (0.00020, 0.00020),
    # Mistral — European foundation models, OpenAI-compatible API.
    "mistral:mistral-large-latest":  (0.002, 0.006),
    "mistral:mistral-medium-latest": (0.0004, 0.002),
    "mistral:mistral-small-latest":  (0.0002, 0.0006),
    "mistral:ministral-8b-latest":   (0.0001, 0.0001),
    "mistral:ministral-3b-latest":   (0.00004, 0.00004),
}


def estimate_cost(vendor: str, model: str, input_tokens: int, output_tokens: int) -> float:
    key = f"{vendor}:{model}"
    if key not in PRICING_PER_1K:
        return 0.0
    in_per_k, out_per_k = PRICING_PER_1K[key]
    return (input_tokens / 1000.0) * in_per_k + (output_tokens / 1000.0) * out_per_k
