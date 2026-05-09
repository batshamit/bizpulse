"""Score one AgentRunResult against a TaskExpectation.

Pure-Python; no LLM calls (LLM-as-judge lives in `llm_judge.py`).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from bizpulse.agents.runner import AgentRunResult
from bizpulse.eval.golden import TaskExpectation


class TaskScore(BaseModel):
    """How one task scored — used both per-task and aggregated."""

    task_id: str
    agent: str
    schema_valid: bool = True   # if we got an AgentRunResult, schema validated
    repair_attempted: bool
    citation_count: int
    citations_meet_min: bool
    keyword_hits: dict[str, bool] = Field(default_factory=dict)
    forbidden_hits: dict[str, bool] = Field(default_factory=dict)
    confidence: float | None = None
    confidence_meets_min: bool = True
    latency_ms: float
    latency_within_budget: bool = True
    cost_usd: float
    cost_within_budget: bool = True
    judge_score: float | None = None
    """Optional LLM-as-judge score in [0,1]. None if judge wasn't run."""

    @property
    def passed(self) -> bool:
        """Hard pass/fail — judge_score is advisory and doesn't gate."""
        return (
            self.schema_valid
            and self.citations_meet_min
            and self.confidence_meets_min
            and self.latency_within_budget
            and self.cost_within_budget
            and not any(self.forbidden_hits.values())
            and all(self.keyword_hits.values())
        )


class ScoreFailure(BaseModel):
    """Returned in place of a TaskScore when the agent never produced output."""

    task_id: str
    agent: str
    error: str
    raw_text: str | None = None
    schema_valid: bool = False
    passed: bool = False


# ---------- helpers --------------------------------------------------------

def _walk(obj: Any) -> Any:
    """Yield every value in a nested dict/list."""
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)
    else:
        yield obj


def extract_cited_chunk_ids(output: BaseModel) -> set[str]:
    """Walk the model dump and pull every chunk_id referenced via either
    Citation.chunk_id or Recommendation.evidence_chunk_ids."""
    found: set[str] = set()
    raw = output.model_dump(mode="json")

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "chunk_id" and isinstance(v, str):
                    found.add(v)
                elif k == "evidence_chunk_ids" and isinstance(v, list):
                    for cid in v:
                        if isinstance(cid, str):
                            found.add(cid)
                visit(v)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(raw)
    return found


def extract_confidence(output: BaseModel) -> float | None:
    """Pull a 'confidence' or 'overall_confidence' field if present."""
    raw = output.model_dump(mode="json")
    if isinstance(raw, dict):
        for key in ("overall_confidence", "confidence"):
            v = raw.get(key)
            if isinstance(v, (int, float)):
                return float(v)
    return None


# ---------- main entry point ---------------------------------------------

def score_task(
    *,
    task_id: str,
    result: AgentRunResult,
    expected: TaskExpectation,
) -> TaskScore:
    out = result.output
    cited = extract_cited_chunk_ids(out)
    citation_count = len(cited)

    raw_json = out.model_dump_json().lower()
    keyword_hits = {kw: kw.lower() in raw_json for kw in expected.must_contain_keywords}
    forbidden_hits = {kw: kw.lower() in raw_json for kw in expected.must_not_contain_keywords}

    confidence = extract_confidence(out)

    return TaskScore(
        task_id=task_id,
        agent=result.agent,
        schema_valid=True,
        repair_attempted=result.repair_attempted,
        citation_count=citation_count,
        citations_meet_min=citation_count >= expected.min_citations,
        keyword_hits=keyword_hits,
        forbidden_hits=forbidden_hits,
        confidence=confidence,
        confidence_meets_min=(
            expected.min_confidence is None
            or (confidence is not None and confidence >= expected.min_confidence)
        ),
        latency_ms=result.latency_ms,
        latency_within_budget=(
            expected.max_latency_ms is None or result.latency_ms <= expected.max_latency_ms
        ),
        cost_usd=result.council.cost_usd,
        cost_within_budget=(
            expected.max_cost_usd is None or result.council.cost_usd <= expected.max_cost_usd
        ),
    )
