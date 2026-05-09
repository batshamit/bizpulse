"""LLM-as-judge — score the *quality* of an agent's output beyond hard checks.

The judge sees: the original task, the retrieved chunks, the agent's output.
It returns a 0-10 score across rubric criteria (groundedness, relevance,
specificity, actionability), plus a one-line rationale. We average the
criteria into a single 0-1 score for `TaskScore.judge_score`.

Operationally cheap: one extra LLM call per scored task, single round
(no debate). The judge can be any LLMClient — typically Claude or GPT-4o
because they're both strong at meta-evaluation.
"""

from __future__ import annotations

import json
from textwrap import dedent

from pydantic import BaseModel, Field

from bizpulse.agents.runner import extract_json
from bizpulse.llm.base import LLMClient
from bizpulse.logging import get_logger
from bizpulse.models.retrieval import RetrievedChunk

log = get_logger(__name__)


class JudgeRubric(BaseModel):
    """Rubric — 0 to 10 each, higher is better."""

    groundedness: float = Field(ge=0.0, le=10.0)
    """Are claims supported by chunks (vs. fabricated)?"""

    relevance: float = Field(ge=0.0, le=10.0)
    """Does the output answer the actual task?"""

    specificity: float = Field(ge=0.0, le=10.0)
    """Are recommendations specific (channels, numbers, examples) or generic?"""

    actionability: float = Field(ge=0.0, le=10.0)
    """Could a marketer act on this tomorrow?"""

    rationale: str = Field(default="")

    @property
    def avg(self) -> float:
        return (self.groundedness + self.relevance + self.specificity + self.actionability) / 4

    @property
    def avg_unit(self) -> float:
        """0..1 normalized average — what TaskScore.judge_score uses."""
        return self.avg / 10.0


_JUDGE_SYSTEM = dedent(
    """
    You are an evaluator of AI marketing-strategy agents. You score the agent's
    output against a rubric. Reply ONLY with JSON in this shape (no prose):
      {
        "groundedness": <number 0-10>,
        "relevance":    <number 0-10>,
        "specificity": <number 0-10>,
        "actionability":<number 0-10>,
        "rationale":   "<one sentence>"
      }
    Be strict. Reserve scores ≥ 9 for outputs that are notably better than
    typical. Penalize hallucinated facts and unsupported numbers.
    """
).strip()


def _format_chunks(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "(no chunks were available to the agent)"
    parts = []
    for rc in chunks:
        meta = rc.chunk.metadata
        parts.append(
            f"[chunk:{rc.chunk.id}] (source={meta.source_url}, "
            f"type={meta.source_type}) {rc.chunk.text}"
        )
    return "\n\n".join(parts)


async def llm_judge_score(
    *,
    judge: LLMClient,
    task_description: str,
    retrieved_chunks: list[RetrievedChunk],
    agent_output_json: str,
) -> JudgeRubric:
    """Run one judging call. Returns a JudgeRubric or raises."""
    user = (
        f"Task the agent had: {task_description}\n\n"
        f"Retrieved context the agent saw:\n{_format_chunks(retrieved_chunks)}\n\n"
        f"Agent's output (JSON):\n{agent_output_json}\n\n"
        "Score the output."
    )
    cr = await judge.complete(system=_JUDGE_SYSTEM, user=user, max_tokens=1024, temperature=0.0)
    try:
        data = extract_json(cr.text)
    except ValueError as exc:
        raise ValueError(f"judge returned unparseable JSON: {cr.text[:200]}") from exc
    return JudgeRubric.model_validate(data)
