"""Tests for the multi-LLM Council debate logic.

All tests use FakeLLMClient / ScriptedLLMClient — zero network. The Council
itself is vendor-neutral; vendor adapters are tested separately when keys
are available.
"""

from __future__ import annotations

import pytest

from bizpulse.agents import Council, CouncilError
from bizpulse.llm import FakeLLMClient, LLMError, ScriptedLLMClient


@pytest.mark.asyncio
async def test_basic_two_round_debate() -> None:
    a = ScriptedLLMClient("a", "fake", responses=["proposal-A1", "revision-A2"])
    b = ScriptedLLMClient("b", "fake", responses=["proposal-B1", "revision-B2"])
    judge = FakeLLMClient(name="judge", vendor="fake", response="SYNTHESIZED")
    c = Council(members=[a, b], judge=judge, rounds=2)

    res = await c.debate(system="sys", user="task")

    assert res.final == "SYNTHESIZED"
    assert res.judge == "judge"
    assert len(res.rounds) == 2
    # Round 1 each member sees only the original task.
    r1 = res.rounds[0]
    assert {p.member for p in r1} == {"a", "b"}
    assert all(p.error is None for p in r1)
    # Round 2 user prompts include the peer-proposal block.
    a_r2_user = a.calls[1].user
    assert "previous round, peer proposals" in a_r2_user
    assert "proposal-B1" in a_r2_user
    assert "proposal-A1" not in a_r2_user.split("----- previous round, peer proposals -----")[1].split("----- end peer proposals -----")[0]  # never sees own
    # Cost is summed across rounds + synthesis.
    assert res.cost_usd > 0


@pytest.mark.asyncio
async def test_member_failure_drops_for_next_round() -> None:
    """A member that fails round 1 must not be called again in round 2, and
    their failure shows up in minority_opinions."""
    good = ScriptedLLMClient("good", "v1", responses=["g1", "g2"])
    bad = FakeLLMClient(
        name="bad",
        vendor="v2",
        raise_on_call=LLMError("boom", vendor="v2", model="bad", retryable=False),
    )
    judge = FakeLLMClient(name="judge", vendor="v3", response="FINAL")

    c = Council(members=[good, bad], judge=judge, rounds=2)
    res = await c.debate(system="sys", user="task")

    assert res.final == "FINAL"
    # Bad was called once (round 1) and never again.
    assert len(bad.calls) == 1
    # Good was called twice — proposal + revision.
    assert len(good.calls) == 2
    # Minority opinions records the drop.
    assert any("bad dropped" in m for m in res.minority_opinions)


@pytest.mark.asyncio
async def test_all_members_fail_judge_still_synthesizes() -> None:
    """When every member errors we should still synthesize from the original
    task (no proposals available — the judge is told to answer directly)."""
    err = LLMError("offline", vendor="v", model="m", retryable=False)
    a = FakeLLMClient(name="a", vendor="v", raise_on_call=err)
    b = FakeLLMClient(name="b", vendor="v", raise_on_call=err)
    judge = FakeLLMClient(name="j", vendor="v", response="SOLO_ANSWER")

    c = Council(members=[a, b], judge=judge, rounds=2)
    res = await c.debate(system="sys", user="task")

    assert res.final == "SOLO_ANSWER"
    # Judge prompt must say "no proposals available".
    assert "No council proposals available" in judge.calls[-1].user


@pytest.mark.asyncio
async def test_judge_failure_uses_fallback() -> None:
    a = FakeLLMClient(name="a", vendor="v", response="A")
    b = FakeLLMClient(name="b", vendor="v", response="B")
    primary_judge = FakeLLMClient(
        name="primary",
        vendor="v",
        raise_on_call=LLMError("rate-limited", vendor="v", model="primary", retryable=True),
    )
    fallback = FakeLLMClient(name="fallback", vendor="v2", response="FALLBACK_OUT")

    c = Council(
        members=[a, b],
        judge=primary_judge,
        fallback_judge=fallback,
        rounds=1,
    )
    res = await c.debate(system="sys", user="task")
    assert res.final == "FALLBACK_OUT"
    assert res.judge == "fallback"
    assert any("judge fallback used" in m for m in res.minority_opinions)


@pytest.mark.asyncio
async def test_judge_failure_no_fallback_raises() -> None:
    a = FakeLLMClient(name="a", vendor="v", response="A")
    primary = FakeLLMClient(
        name="primary",
        vendor="v",
        raise_on_call=LLMError("dead", vendor="v", model="primary", retryable=False),
    )
    c = Council(members=[a], judge=primary, rounds=1)
    with pytest.raises(CouncilError):
        await c.debate(system="sys", user="task")


@pytest.mark.asyncio
async def test_empty_members_rejected() -> None:
    judge = FakeLLMClient(name="j", vendor="v", response="x")
    with pytest.raises(ValueError):
        Council(members=[], judge=judge)


@pytest.mark.asyncio
async def test_zero_rounds_rejected() -> None:
    a = FakeLLMClient(name="a", vendor="v", response="x")
    judge = FakeLLMClient(name="j", vendor="v", response="x")
    with pytest.raises(ValueError):
        Council(members=[a], judge=judge, rounds=0)
