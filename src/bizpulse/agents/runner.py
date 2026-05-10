"""AgentRunner — the bridge from a high-level task to a typed Pydantic output.

Per call:
  1. PromptBuilder assembles (system, user) for the target agent role with
     industry-pack injection and chunk-cited context.
  2. RetrievalEngine.search() fetches the context chunks (filtered to tenant).
  3. Council.debate() runs N-round multi-vendor reasoning + synthesis.
  4. The synthesizer's text is parsed as JSON and validated against the
     supplied Pydantic schema. Parse failure triggers one repair attempt
     where we re-prompt the judge with the validation error included.

This is the helper every analytical agent (BrandAnalyst, AudienceAnalyst,
Strategist, Critic, ...) calls. Each agent is just a thin wrapper that
picks its schema and writes its task string.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from bizpulse.agents.council import Council, CouncilResult
from bizpulse.agents.prompts import PromptBuilder
from bizpulse.logging import get_logger
from bizpulse.models.agents import AgentName
from bizpulse.models.industry import IndustryPack, load_industry
from bizpulse.models.retrieval import RetrievalQuery, RetrievedChunk
from bizpulse.retrieval.search import RetrievalEngine

log = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


# ---- result type --------------------------------------------------------

@dataclass
class AgentRunResult(Generic[T]):
    """One full run of one agent. The interesting bit for callers is `output`;
    the rest is audit trail for the Critic and the failure-replay UI."""

    agent: AgentName
    output: T
    council: CouncilResult
    context_chunks: list[RetrievedChunk] = field(default_factory=list)
    repair_attempted: bool = False
    latency_ms: float = 0.0


class AgentRunError(RuntimeError):
    """Raised when the agent failed to produce schema-valid output even after
    one repair attempt."""

    def __init__(self, message: str, *, raw_text: str, validation_error: str | None = None) -> None:
        super().__init__(message)
        self.raw_text = raw_text
        self.validation_error = validation_error


# ---- JSON extraction ----------------------------------------------------

_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)
_OBJECT_RE = re.compile(r"(\{.*\}|\[.*\])", re.DOTALL)


def extract_json(text: str) -> object:
    """Best-effort JSON extraction from a model response.

    Tries: (1) direct, (2) fenced code block, (3) first {...} or [...] in text.
    Raises ValueError if no parseable JSON found.
    """
    text = text.strip()
    # 1. direct
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 2. fenced
    m = _FENCE_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 3. greedy first { ... } block
    m = _OBJECT_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    raise ValueError(f"no parseable JSON in response: {text[:200]}")


# ---- runner ------------------------------------------------------------

class AgentRunner:
    """Bind a tenant context (retrieval, prompts, council) and run agents."""

    def __init__(
        self,
        retrieval: RetrievalEngine,
        council: Council,
        *,
        industry: str | None = None,
        prompt_builder: PromptBuilder | None = None,
    ) -> None:
        self.retrieval = retrieval
        self.council = council
        self.industry = industry
        if prompt_builder is not None:
            self.prompts = prompt_builder
        else:
            pack: IndustryPack | None = None
            if industry:
                try:
                    pack = load_industry(industry)
                except FileNotFoundError:
                    log.warning("agent_runner.unknown_industry", industry=industry)
            self.prompts = PromptBuilder(industry_pack=pack)

    async def run(
        self,
        *,
        agent: AgentName,
        task: str,
        output_schema: type[T],
        query_text: str,
        top_k: int = 8,
    ) -> AgentRunResult[T]:
        """Run one agent end-to-end. Returns typed output + audit trail."""
        t0 = time.perf_counter()

        # 1. Retrieve context.
        rq = RetrievalQuery(
            text=query_text,
            tenant_id=self.retrieval.repo.tenant_id,
            industry=self.industry,
            top_k=top_k,
        )
        retrieval_result = await self.retrieval.search(rq)
        context_chunks = retrieval_result.chunks

        # 2. Build prompts. Embed the JSON schema so weaker models don't
        #    invent field names. We strip a couple of noisy keys (title,
        #    description) to keep the prompt compact.
        schema_json = json.dumps(_compact_schema(output_schema), indent=2)
        system, user = self.prompts.build(
            agent=agent,
            task=task,
            context_chunks=context_chunks,
            output_schema_name=output_schema.__name__,
            output_schema_json=schema_json,
        )

        # 3. Run debate.
        council_result = await self.council.debate(system=system, user=user)

        # 4. Parse + validate output.
        repaired = False
        try:
            data = extract_json(council_result.final)
            output = output_schema.model_validate(data)
        except (ValueError, ValidationError) as first_err:
            # One repair attempt: re-ask the judge with the error attached.
            log.warning(
                "agent_runner.parse_failed_attempting_repair",
                agent=agent,
                error=str(first_err)[:200],
            )
            repaired = True
            try:
                output = await self._repair(
                    council_result=council_result,
                    output_schema=output_schema,
                    system=system,
                    error=str(first_err),
                )
            except (ValueError, ValidationError) as second_err:
                raise AgentRunError(
                    f"agent {agent} failed to produce {output_schema.__name__} "
                    f"after one repair attempt",
                    raw_text=council_result.final,
                    validation_error=str(second_err),
                ) from second_err

        latency_ms = (time.perf_counter() - t0) * 1000.0
        return AgentRunResult(
            agent=agent,
            output=output,
            council=council_result,
            context_chunks=context_chunks,
            repair_attempted=repaired,
            latency_ms=latency_ms,
        )

    async def _repair(
        self,
        *,
        council_result: CouncilResult,
        output_schema: type[T],
        system: str,
        error: str,
    ) -> T:
        """Re-ask the judge for a corrected JSON output, given the validation error."""
        schema_json = json.dumps(_compact_schema(output_schema), indent=2)
        repair_user = (
            f"Your previous response did not pass schema validation against "
            f"{output_schema.__name__}. The error was:\n\n{error}\n\n"
            f"The exact JSON Schema is:\n```json\n{schema_json}\n```\n\n"
            f"Your previous text was:\n\n{council_result.final}\n\n"
            "Reply with ONLY a corrected JSON object that matches the schema "
            "exactly. Use the field names from the schema (case-sensitive). "
            "No prose, no fences, no extra fields."
        )
        cr = await self.council.judge.complete(
            system=system, user=repair_user, max_tokens=4096, temperature=0.0
        )
        data = extract_json(cr.text)
        return output_schema.model_validate(data)


def _compact_schema(model: type[BaseModel]) -> dict[str, object]:
    """Strip noisy keys (title, description, examples) from a Pydantic model
    JSON schema so the prompt stays focused on shape."""
    schema = model.model_json_schema()

    def strip(node: object) -> object:
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                if k in {"title", "description", "examples"}:
                    continue
                out[k] = strip(v)
            return out
        if isinstance(node, list):
            return [strip(v) for v in node]
        return node

    return strip(schema)  # type: ignore[return-value]
