"""Eval harness — golden examples, scorer, LLM-as-judge, runner."""

from __future__ import annotations

from bizpulse.eval.golden import (
    GoldenChunk,
    GoldenExample,
    GoldenTask,
    TaskExpectation,
    discover_golden,
    load_golden,
)
from bizpulse.eval.llm_judge import JudgeRubric, llm_judge_score
from bizpulse.eval.runner import EvalReport, EvalRunner
from bizpulse.eval.scorer import (
    ScoreFailure,
    TaskScore,
    extract_cited_chunk_ids,
    extract_confidence,
    score_task,
)

__all__ = [
    "EvalReport",
    "EvalRunner",
    "GoldenChunk",
    "GoldenExample",
    "GoldenTask",
    "JudgeRubric",
    "ScoreFailure",
    "TaskExpectation",
    "TaskScore",
    "discover_golden",
    "extract_cited_chunk_ids",
    "extract_confidence",
    "llm_judge_score",
    "load_golden",
    "score_task",
]
