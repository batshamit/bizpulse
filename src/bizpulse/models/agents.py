"""Agent-IO contracts — every agent has a typed input + output schema."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field

from bizpulse.models.citations import Citation
from bizpulse.models.common import BusinessId, StrictModel, TenantId, utcnow
from bizpulse.models.retrieval import RetrievedChunk

AgentName = Literal[
    "orchestrator",
    "industry_classifier",
    "brand_analyst",
    "audience_analyst",
    "competitor_scout",
    "content_auditor",
    "strategist",
    "critic",
    "audience_simulator",  # Phase-2 MiroFish, optional
]

AgentStatus = Literal["ok", "retry", "failed"]


class AgentInput(StrictModel):
    """Common envelope for every agent call."""

    agent: AgentName
    task: str = Field(min_length=1, description="Human-readable task summary, for logging.")
    tenant_id: TenantId
    business_id: BusinessId
    industry: str | None = None
    context_chunks: list[RetrievedChunk] = Field(default_factory=list)
    constraints: dict[str, str] = Field(default_factory=dict)
    retry_count: int = Field(default=0, ge=0)
    max_retries: int = Field(default=2, ge=0, le=5)


class AgentOutput(StrictModel):
    """Common envelope every agent's structured payload sits inside.

    Subclasses (in `models.strategy`) are the actual analytical results;
    they're attached as `payload` (typed via discriminated unions there).
    Citations are required for any agent that produces analytical findings —
    the Critic enforces this; here we only require the field exist.
    """

    agent: AgentName
    status: AgentStatus
    error: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    retry_count: int = Field(default=0, ge=0)
    fallback_used: bool = Field(
        default=False,
        description="True if the primary model failed and we fell back to Anthropic/OpenAI.",
    )


class AgentTrace(StrictModel):
    """Persisted log of one agent call — for the failure-replay UI."""

    id: UUID = Field(default_factory=uuid4)
    agent: AgentName
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    duration_ms: float | None = Field(default=None, ge=0.0)
    prompt: str
    response: str
    retries: int = Field(default=0, ge=0)
    status: AgentStatus
    error: str | None = None
    fallback_used: bool = False
