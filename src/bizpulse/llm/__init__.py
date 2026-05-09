"""LLM client layer — vendor-neutral interface + per-vendor implementations.

A note on naming: the project plan and JD use 'multi-agent' for the LangGraph
nodes (one per analytical role). We add a second axis here: each agent role
can be backed by a *Council of LLMs* — multiple vendors that debate, with a
synthesizer producing the final structured output. See `bizpulse.agents.council`.
"""

from __future__ import annotations

from bizpulse.llm.base import (
    PRICING_PER_1K,
    CompletionResult,
    LLMClient,
    LLMError,
    estimate_cost,
)
from bizpulse.llm.fakes import (
    CallableLLMClient,
    FakeLLMClient,
    ScriptedLLMClient,
)

# Vendor adapters are imported lazily inside factory.* — they pull in
# heavy SDKs (anthropic, httpx) that should not fail on missing optional
# config.

__all__ = [
    "PRICING_PER_1K",
    "CallableLLMClient",
    "CompletionResult",
    "FakeLLMClient",
    "LLMClient",
    "LLMError",
    "ScriptedLLMClient",
    "estimate_cost",
]
