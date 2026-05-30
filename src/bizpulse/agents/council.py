"""Council of LLMs — a multi-vendor debate that converges on one answer.

Pattern (Du et al., "Improving Factuality and Reasoning in LMs through
Multiagent Debate", 2023, adapted):

  Round 1   each member answers the task independently (parallel).
  Round 2..N
            each member sees the OTHER members' previous-round answers and
            revises their own. They are asked to mark agreements and
            disagreements explicitly. Members run in parallel within a round.
  Synthesize
            a designated `judge` LLM takes the final-round proposals and
            emits ONE schema-validated answer plus a `minority_opinions`
            appendix listing what got vetoed and why.

Why bother:
  - Hallucination defense — outliers get outvoted.
  - Vendor diversity — Anthropic outage, OpenAI rate-limit, Gemini quota all
    degrade the council gracefully (failed members are dropped, not retried).
  - Specialization — Perplexity contributes web search; DeepSeek-R1 contributes
    explicit reasoning chains; Grok contributes X/Twitter signal.

Failure semantics:
  - If a member errors mid-round, we drop them for subsequent rounds and
    record the error in `minority_opinions`. A council can still converge
    with N-1 members.
  - If the judge errors, we fall back to a configurable `fallback_judge`
    (typically Claude). If both error, the council raises CouncilError.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

from bizpulse.llm.base import CompletionResult, LLMClient, LLMError
from bizpulse.logging import get_logger

log = get_logger(__name__)


# --- result types ----------------------------------------------------------


@dataclass(frozen=True)
class ProposalRecord:
    """One member's response in one round."""

    member: str  # member.name
    vendor: str
    round_idx: int  # 0 == first round
    text: str
    cost_usd: float
    latency_ms: float
    error: str | None = None  # if member raised, text=='' and error set


@dataclass
class CouncilResult:
    final: str  # synthesizer's text (caller validates against schema)
    judge: str  # judge.name that synthesized
    rounds: list[list[ProposalRecord]] = field(default_factory=list)
    minority_opinions: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    latency_ms: float = 0.0


class CouncilError(RuntimeError):
    """Raised when the council can't produce a final answer (judge fails too)."""


# --- the council -----------------------------------------------------------


class Council:
    """A debate-based multi-LLM ensemble.

    Members and judge are injected. The judge can be one of the members or a
    separate client. Use `fallback_judge` to handle judge-side outages.
    """

    def __init__(
        self,
        members: Sequence[LLMClient],
        judge: LLMClient,
        *,
        fallback_judge: LLMClient | None = None,
        rounds: int = 2,
        round_temperature: float = 0.2,
        synthesis_temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> None:
        if not members:
            raise ValueError("Council needs at least one member")
        if rounds < 1:
            raise ValueError("rounds must be >= 1")
        if max_tokens < 256:
            raise ValueError("max_tokens must be >= 256")
        self.members = list(members)
        self.judge = judge
        self.fallback_judge = fallback_judge
        self.fallback_judges: list[LLMClient] = []
        if fallback_judge is not None:
            self.fallback_judges.append(fallback_judge)
        for m in self.members:
            if m.name != judge.name and (fallback_judge is None or m.name != fallback_judge.name):
                self.fallback_judges.append(m)
        self.rounds = rounds
        self.round_temperature = round_temperature
        self.synthesis_temperature = synthesis_temperature
        self.max_tokens = max_tokens

    async def debate(self, system: str, user: str) -> CouncilResult:
        t0 = time.perf_counter()
        rounds: list[list[ProposalRecord]] = []
        minority: list[str] = []
        active_members = list(self.members)

        # ----- proposal & revision rounds -----
        for round_idx in range(self.rounds):
            prev = rounds[-1] if rounds else None
            results = await self._run_round(active_members, system, user, prev, round_idx)
            rounds.append(results)

            # Drop members that errored — they don't participate next round.
            failed = [r for r in results if r.error]
            if failed:
                active_members = [
                    m for m in active_members if not any(f.member == m.name for f in failed)
                ]
                for f in failed:
                    minority.append(f"{f.member} dropped (round {round_idx}): {f.error}")

            if not active_members:
                # Everyone failed. We can still try to synthesize from prior rounds.
                break

        # ----- synthesis -----
        final_round = rounds[-1] if rounds else []
        synth_user = self._build_synthesis_user(user, final_round)
        try:
            synth = await self.judge.complete(
                system=self._synthesis_system(system),
                user=synth_user,
                max_tokens=self.max_tokens,
                temperature=self.synthesis_temperature,
            )
            judge_used = self.judge.name
        except (LLMError, Exception) as exc:
            log.warning("council.judge_failed", judge=self.judge.name, error=str(exc)[:200])
            synth = None
            last_err = exc
            for fb in self.fallback_judges:
                try:
                    synth = await fb.complete(
                        system=self._synthesis_system(system),
                        user=synth_user,
                        max_tokens=self.max_tokens,
                        temperature=self.synthesis_temperature,
                    )
                    judge_used = fb.name
                    minority.append(
                        f"judge fallback used: primary={self.judge.name} failed -> {fb.name} due to {type(exc).__name__}: {str(exc)[:150]}"
                    )
                    break
                except Exception as fb_exc:
                    log.warning(
                        "council.fallback_judge_failed", judge=fb.name, error=str(fb_exc)[:200]
                    )
                    last_err = fb_exc
            if synth is None:
                raise CouncilError(
                    f"judge {self.judge.name} failed and all fallbacks failed. Last error: {last_err}"
                ) from last_err

        assert synth is not None
        total_cost = synth.cost_usd + sum(p.cost_usd for r in rounds for p in r)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        return CouncilResult(
            final=synth.text,
            judge=judge_used,
            rounds=rounds,
            minority_opinions=minority,
            cost_usd=total_cost,
            latency_ms=latency_ms,
        )

    # ---------- internals -----------------------------------------------

    async def _run_round(
        self,
        members: Sequence[LLMClient],
        system: str,
        base_user: str,
        prev_round: list[ProposalRecord] | None,
        round_idx: int,
    ) -> list[ProposalRecord]:
        async def _one(m: LLMClient) -> ProposalRecord:
            # Each member sees PEERS' proposals (not their own).
            this_user = (
                base_user
                if prev_round is None
                else self._build_revision_user(base_user, prev_round, exclude_member=m.name)
            )
            try:
                cr: CompletionResult = await m.complete(
                    system=system,
                    user=this_user,
                    max_tokens=self.max_tokens,
                    temperature=self.round_temperature,
                )
                return ProposalRecord(
                    member=m.name,
                    vendor=m.vendor,
                    round_idx=round_idx,
                    text=cr.text,
                    cost_usd=cr.cost_usd,
                    latency_ms=cr.latency_ms,
                )
            except Exception as exc:  # broad: vendor SDKs raise heterogeneously
                log.warning(
                    "council.member_failed",
                    member=m.name,
                    round=round_idx,
                    error=str(exc)[:200],
                )
                return ProposalRecord(
                    member=m.name,
                    vendor=m.vendor,
                    round_idx=round_idx,
                    text="",
                    cost_usd=0.0,
                    latency_ms=0.0,
                    error=type(exc).__name__ + ": " + str(exc)[:200],
                )

        return await asyncio.gather(*(_one(m) for m in members))

    @staticmethod
    def _build_revision_user(
        original_user: str,
        prev_round: list[ProposalRecord],
        exclude_member: str | None = None,
    ) -> str:
        """Build a revision-round user prompt for one specific member.

        `exclude_member` is the calling member's name — we filter out their
        own previous-round proposal so they only see peers'.
        """
        survivors = [
            p
            for p in prev_round
            if not p.error and (exclude_member is None or p.member != exclude_member)
        ]
        if not survivors:
            return original_user
        peer_block = "\n\n".join(f"--- proposal from {p.member} ---\n{p.text}" for p in survivors)
        return (
            f"{original_user}\n\n"
            "----- previous round, peer proposals -----\n"
            f"{peer_block}\n"
            "----- end peer proposals -----\n\n"
            "Re-do your answer. Where peers raise points you missed or got "
            "wrong, incorporate them. Where peers are wrong, push back and "
            "say why. Stay concise. Output the same JSON schema as before."
        )

    @staticmethod
    def _build_synthesis_user(original_user: str, final_round: list[ProposalRecord]) -> str:
        survivors = [p for p in final_round if not p.error]
        if not survivors:
            return original_user + "\n\nNo council proposals available — answer directly."
        proposals_block = "\n\n".join(
            f"--- {p.member} (vendor={p.vendor}) ---\n{p.text}" for p in survivors
        )
        return (
            f"{original_user}\n\n"
            "----- council final-round proposals -----\n"
            f"{proposals_block}\n"
            "----- end proposals -----\n\n"
            "Synthesize ONE final answer that incorporates the strongest, "
            "most-grounded points from the council. Where members disagreed, "
            "pick the side with stronger evidence (citations, retrieved chunks). "
            "Output ONLY valid JSON matching the schema in the original task."
        )

    @staticmethod
    def _synthesis_system(original_system: str) -> str:
        return (
            f"{original_system}\n\n"
            "You are also acting as the JUDGE of a multi-LLM council. Your "
            "synthesis MUST be schema-valid JSON. Citations from any council "
            "member's proposal that traces to a real chunk_id in the retrieved "
            "context may be carried forward; invented chunk_ids must be dropped."
        )
