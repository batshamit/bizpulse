"""EvalRunner — load a GoldenExample, run every task, score them, aggregate.

The runner is intentionally simple:
  1. Spin up a synthetic tenant in the supplied store.
  2. Embed the golden chunks via the supplied embedder; upsert into Qdrant.
  3. For each task, build an AgentRunner and run() it.
  4. Score the result with `score_task` and (if a judge is supplied) the
     LLM judge.
  5. Aggregate task scores into an EvalReport.

Caller injects everything (store, embedder, Qdrant client, council factory),
so the runner doesn't care whether it's running against fakes or live LLMs.
"""

from __future__ import annotations

import importlib
import time
from typing import Callable, Mapping
from uuid import uuid4

from pydantic import BaseModel, Field

from bizpulse.agents import AgentRunError, AgentRunner, Council
from bizpulse.eval.golden import GoldenExample, GoldenTask
from bizpulse.eval.llm_judge import JudgeRubric, llm_judge_score
from bizpulse.eval.scorer import ScoreFailure, TaskScore, score_task
from bizpulse.ingest.pipeline import EmbedderProtocol, IngestionPipeline
from bizpulse.llm.base import LLMClient
from bizpulse.logging import get_logger
from bizpulse.models import RawArtifact
from bizpulse.models.common import utcnow
from bizpulse.retrieval import TenantQdrant
from bizpulse.retrieval.search import RetrievalEngine

log = get_logger(__name__)


class EvalReport(BaseModel):
    """One eval run across one golden example. Persisted as JSON."""

    golden_id: str
    industry: str
    started_at: str
    finished_at: str
    total_latency_ms: float
    total_cost_usd: float
    n_tasks: int
    n_passed: int
    task_scores: list[TaskScore | ScoreFailure] = Field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return (self.n_passed / self.n_tasks) if self.n_tasks else 0.0


class EvalRunner:
    """Run a GoldenExample against a Council via AgentRunner."""

    def __init__(
        self,
        *,
        embedder: EmbedderProtocol,
        qdrant_client_factory: Callable[[], object],
        council_factory: Callable[[], Council],
        llm_judge: LLMClient | None = None,
    ) -> None:
        """`qdrant_client_factory` returns a fresh QdrantClient per golden so
        runs are isolated. Use `lambda: QdrantClient(path=tmpdir)` for tests
        or `lambda: QdrantClient(url=...)` for live."""
        self.embedder = embedder
        self.qdrant_client_factory = qdrant_client_factory
        self.council_factory = council_factory
        self.llm_judge = llm_judge

    async def run(self, golden: GoldenExample) -> EvalReport:
        started = utcnow()
        t0 = time.perf_counter()

        # 1. Spin up an isolated tenant for this golden.
        tenant_id = uuid4()
        business_id = uuid4()
        repo = TenantQdrant(tenant_id, client=self.qdrant_client_factory())  # type: ignore[arg-type]
        log.info("eval.golden.start", golden_id=golden.id, industry=golden.industry)

        # 2. Ingest synthetic chunks.
        artifact = _golden_to_artifact(golden, tenant_id, business_id)
        pipe = IngestionPipeline(repo, self.embedder, industry=golden.industry)
        n_chunks = await pipe.ingest([artifact])
        log.info("eval.golden.ingested", chunks=n_chunks)

        # 3. Build runner + run each task.
        retrieval = RetrievalEngine(repo, embedder=self.embedder)  # type: ignore[arg-type]
        council = self.council_factory()
        runner = AgentRunner(retrieval=retrieval, council=council, industry=golden.industry)

        scores: list[TaskScore | ScoreFailure] = []
        total_cost = 0.0
        for task in golden.tasks:
            schema_cls = _resolve_schema(task.output_schema)
            try:
                result = await runner.run(
                    agent=task.agent,
                    task=task.task,
                    output_schema=schema_cls,
                    query_text=task.query_text,
                )
            except AgentRunError as exc:
                scores.append(ScoreFailure(
                    task_id=task.id,
                    agent=task.agent,
                    error=str(exc),
                    raw_text=exc.raw_text[:1000],
                ))
                continue

            ts = score_task(task_id=task.id, result=result, expected=task.expected)

            # 4. Optional LLM judge.
            if self.llm_judge is not None:
                try:
                    rubric: JudgeRubric = await llm_judge_score(
                        judge=self.llm_judge,
                        task_description=task.task,
                        retrieved_chunks=result.context_chunks,
                        agent_output_json=result.output.model_dump_json(),
                    )
                    ts = ts.model_copy(update={"judge_score": rubric.avg_unit})
                except Exception as exc:  # noqa: BLE001 - judge is advisory
                    log.warning("eval.judge_failed", task_id=task.id, error=str(exc)[:200])

            scores.append(ts)
            total_cost += ts.cost_usd

        finished = utcnow()
        latency_ms = (time.perf_counter() - t0) * 1000.0
        n_passed = sum(1 for s in scores if isinstance(s, TaskScore) and s.passed)

        return EvalReport(
            golden_id=golden.id,
            industry=golden.industry,
            started_at=started.isoformat(),
            finished_at=finished.isoformat(),
            total_latency_ms=latency_ms,
            total_cost_usd=total_cost,
            n_tasks=len(golden.tasks),
            n_passed=n_passed,
            task_scores=scores,
        )


# ---- helpers --------------------------------------------------------------

def _golden_to_artifact(golden: GoldenExample, tenant_id, business_id) -> RawArtifact:
    """Glue all chunk texts together as one artifact text. The chunker will
    re-split on paragraph boundaries; we use double-newlines to preserve
    section boundaries so 'section' metadata behaves naturally."""
    text = "\n\n".join(c.text for c in golden.chunks)
    return RawArtifact(
        tenant_id=tenant_id,
        business_id=business_id,
        source_url=golden.business_url,
        source_type="website_page",
        content_hash=RawArtifact.hash_text(text),
        extracted_text=text,
    )


_SCHEMA_CACHE: dict[str, type[BaseModel]] = {}


def _resolve_schema(name: str) -> type[BaseModel]:
    """Resolve 'BrandAnalysis' → bizpulse.models.BrandAnalysis."""
    if name in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[name]
    mod = importlib.import_module("bizpulse.models")
    if not hasattr(mod, name):
        raise KeyError(f"unknown output_schema: {name}")
    cls = getattr(mod, name)
    if not isinstance(cls, type) or not issubclass(cls, BaseModel):
        raise TypeError(f"{name} is not a Pydantic BaseModel")
    _SCHEMA_CACHE[name] = cls
    return cls
