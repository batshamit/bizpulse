"""Build a Council from whichever vendor API keys are present in the env.

Usage:
    from bizpulse.llm.factory import build_council
    council = build_council(judge_preference=["anthropic", "google"])

Returns a `Council` whose members are exactly the vendors with available
keys. Skips silently when a key is missing — the council degrades to as
few as one member.
"""

from __future__ import annotations

import os
from typing import Sequence

from bizpulse.agents.council import Council
from bizpulse.llm.base import LLMClient

# Module-level imports of vendor adapters are deferred until needed so
# missing optional deps don't break the package import.


def _try_anthropic(model: str | None = None) -> LLMClient | None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        from bizpulse.llm.anthropic_client import AnthropicClient
        return AnthropicClient(model=model or "claude-sonnet-4-6")
    except Exception:
        return None


def _try_openai_compat(
    factory_name: str,
    env_var: str,
    default_model: str | None = None,
) -> LLMClient | None:
    if not os.environ.get(env_var):
        return None
    try:
        from bizpulse.llm import openai_compat as oc
        factory = getattr(oc, factory_name)
        return factory(model=default_model) if default_model else factory()
    except Exception:
        return None


def _try_gemini(model: str | None = None) -> LLMClient | None:
    if not (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")):
        return None
    try:
        from bizpulse.llm.gemini_client import GeminiClient
        return GeminiClient(model=model or "gemini-2.5-pro")
    except Exception:
        return None


# Vendor → builder. Order matters: this is the default convening order.
VENDOR_BUILDERS: dict[str, callable] = {
    "anthropic":  _try_anthropic,
    "google":     _try_gemini,
    "openai":     lambda: _try_openai_compat("OpenAIClient", "OPENAI_API_KEY"),
    "perplexity": lambda: _try_openai_compat("PerplexityClient", "PERPLEXITY_API_KEY"),
    "xai":        lambda: _try_openai_compat("GrokClient", "XAI_API_KEY"),
    "deepseek":   lambda: _try_openai_compat("DeepSeekClient", "DEEPSEEK_API_KEY"),
    "groq":       lambda: _try_openai_compat("GroqClient", "GROQ_API_KEY"),
}


def available_vendors() -> list[str]:
    """Vendors whose API key is currently set."""
    return [
        v for v, builder in VENDOR_BUILDERS.items()
        if builder() is not None
    ]


def build_clients(prefer: Sequence[str] | None = None) -> list[LLMClient]:
    """Build one client per available vendor, in `prefer` order if given."""
    order = list(prefer) if prefer else list(VENDOR_BUILDERS)
    clients: list[LLMClient] = []
    for v in order:
        builder = VENDOR_BUILDERS.get(v)
        if builder is None:
            continue
        client = builder()
        if client is not None:
            clients.append(client)
    return clients


def build_council(
    *,
    judge_preference: Sequence[str] = ("anthropic", "google", "openai"),
    rounds: int = 2,
    fallback_judge_preference: Sequence[str] = ("openai", "google", "anthropic"),
) -> Council:
    """Build a Council from whatever vendors have keys.

    The judge is the first vendor in `judge_preference` that's available.
    The fallback judge is the first vendor in `fallback_judge_preference`
    that's NOT the primary judge and is available.
    Members are everyone available (including the judge — that's fine; the
    judge can still propose like any other member, then synthesize at the
    end).
    """
    members = build_clients()
    if not members:
        raise RuntimeError(
            "No LLM API keys found. Set at least one of: "
            "ANTHROPIC_API_KEY, GOOGLE_API_KEY, OPENAI_API_KEY, "
            "PERPLEXITY_API_KEY, XAI_API_KEY, DEEPSEEK_API_KEY."
        )

    by_vendor = {m.vendor: m for m in members}

    judge: LLMClient | None = None
    for v in judge_preference:
        if v in by_vendor:
            judge = by_vendor[v]
            break
    if judge is None:
        judge = members[0]

    fallback: LLMClient | None = None
    for v in fallback_judge_preference:
        if v in by_vendor and by_vendor[v] is not judge:
            fallback = by_vendor[v]
            break

    return Council(members=members, judge=judge, fallback_judge=fallback, rounds=rounds)
