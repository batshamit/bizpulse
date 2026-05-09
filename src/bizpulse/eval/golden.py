"""Golden-example schema for the eval harness.

Each golden file exercises one or more agents against a frozen, hand-curated
context. The runner sets up a synthetic tenant, ingests the chunks, and runs
each task through AgentRunner. The Scorer then checks the output.

Format chosen so the JSON is hand-editable in 2 minutes by anyone who
understands the project."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator

from bizpulse.models.agents import AgentName
from bizpulse.models.common import SUPPORTED_INDUSTRIES, StrictModel
from bizpulse.models.ingest import SourceType


class GoldenChunk(StrictModel):
    """One chunk seeded into the synthetic tenant for the run."""

    text: Annotated[str, Field(min_length=1, max_length=8000)]
    source_type: SourceType
    source_url: Annotated[str, Field(min_length=4)]
    section: str | None = None


class TaskExpectation(StrictModel):
    """Pass/fail bar for one task. All fields are optional — the scorer
    only checks the ones supplied."""

    min_citations: int = Field(default=1, ge=0)
    """Minimum number of distinct chunk IDs cited in the output."""

    min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    """If the output has a 'confidence' or 'overall_confidence' field, it
    must be at least this."""

    must_contain_keywords: list[str] = Field(default_factory=list)
    """Each keyword must appear (case-insensitive) somewhere in the output's
    serialized JSON."""

    must_not_contain_keywords: list[str] = Field(default_factory=list)
    """Negative keywords — a hit on any of these fails the task. Used to
    catch fabricated entities (competitors that don't exist, regulators
    misnamed, etc.)."""

    max_latency_ms: float | None = Field(default=None, ge=0.0)
    max_cost_usd: float | None = Field(default=None, ge=0.0)


class GoldenTask(StrictModel):
    """One agent invocation inside a golden example."""

    id: Annotated[str, Field(min_length=1)]
    agent: AgentName
    task: Annotated[str, Field(min_length=1)]
    query_text: Annotated[str, Field(min_length=1)]
    output_schema: Annotated[str, Field(min_length=1)]
    """Pydantic class name in `bizpulse.models` (e.g., 'BrandAnalysis')."""
    expected: TaskExpectation = Field(default_factory=TaskExpectation)


class GoldenExample(StrictModel):
    """One whole eval scenario."""

    id: Annotated[str, Field(min_length=1)]
    industry: str
    business_url: Annotated[str, Field(min_length=4)]
    description: str = ""
    chunks: list[GoldenChunk] = Field(min_length=1)
    tasks: list[GoldenTask] = Field(min_length=1)

    @field_validator("industry")
    @classmethod
    def _industry_supported(cls, v: str) -> str:
        if v not in SUPPORTED_INDUSTRIES:
            msg = f"unsupported industry {v!r}"
            raise ValueError(msg)
        return v


# ----- loader -----------------------------------------------------------

GOLDEN_ROOT = Path(__file__).resolve().parents[3] / "tests" / "eval" / "golden"


def load_golden(path: str | Path) -> GoldenExample:
    p = Path(path)
    if not p.is_absolute():
        p = GOLDEN_ROOT / p
    return GoldenExample.model_validate_json(p.read_text(encoding="utf-8"))


def discover_golden(industry: str | None = None) -> list[Path]:
    """Find all `*.json` golden files. If `industry` is set, restrict to that subdir."""
    base = GOLDEN_ROOT
    if industry:
        base = base / industry
    if not base.is_dir():
        return []
    return sorted(base.rglob("*.json"))
