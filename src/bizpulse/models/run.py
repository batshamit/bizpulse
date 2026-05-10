"""Run records — one analysis pipeline execution end-to-end."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from bizpulse.models.agents import AgentTrace
from bizpulse.models.common import BusinessId, RunId, StrictModel, TenantId, utcnow
from bizpulse.models.strategy import MarketingStrategy

RunStatus = Literal[
    "pending",
    "ingesting",
    "embedding",
    "analyzing",
    "synthesizing",
    "critic_review",
    "complete",
    "failed",
]


class RunRecord(StrictModel):
    """Persisted in Postgres `runs` table (added in a later migration).

    The `agent_traces` list is what the failure-replay debug UI reads.
    `final_output` is None until the Critic accepts the synthesis.
    Cost / token totals are populated by runner_service after the LangGraph
    completes, summing across every Council call.
    """

    id: RunId
    tenant_id: TenantId
    business_id: BusinessId
    status: RunStatus = "pending"
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    agent_traces: list[AgentTrace] = Field(default_factory=list)
    error: str | None = None
    final_output: MarketingStrategy | None = None
    total_input_tokens: int = Field(default=0, ge=0)
    total_output_tokens: int = Field(default=0, ge=0)
    total_cost_usd: float = Field(default=0.0, ge=0.0)
    llm_call_count: int = Field(default=0, ge=0)
