from uuid import uuid4
import os
import pytest
from bizpulse.storage.memory import InMemoryStore
from bizpulse.storage.postgres import PostgresStore
from bizpulse.models.strategy import MarketingStrategy
from bizpulse.models.common import utcnow
from bizpulse.api.runner_service import _persist_final_output

def _test_store_get_successful_runs_by_industry(store):
    industry_name = f"fintech-{uuid4().hex[:6]}"
    tenant = store.create_tenant(name="Few Shot Tenant", slug=f"few-shot-{uuid4().hex[:6]}")
    biz = store.create_business(tenant.id, url="https://test.example", industry=industry_name)
    
    # 1. Check that successful runs is empty initially
    runs = store.get_successful_runs_by_industry(industry_name)
    assert len(runs) == 0
    
    # 2. Create a run
    run = store.create_run(tenant.id, biz.id)
    assert run.status == "pending"
    
    # 3. Complete the run status
    store.update_run_status(run.id, "complete")
    
    # 4. Persist strategy output
    dummy_strategy = MarketingStrategy.model_validate({
        "tenant_id": str(tenant.id),
        "business_id": str(biz.id),
        "industry": industry_name,
        "recommendations": [
            {
                "channel": "linkedin",
                "action": "action",
                "rationale": "rationale",
                "evidence_chunk_ids": [str(uuid4())],
                "confidence": 0.9
            }
        ],
        "overall_confidence": 0.9,
        "summary": "summary"
    })
    _persist_final_output(store=store, run_id=run.id, strategy=dummy_strategy)
    
    # 5. Check if it's retrieved
    runs = store.get_successful_runs_by_industry(industry_name)
    assert len(runs) == 1
    assert runs[0].id == run.id
    assert runs[0].final_output is not None
    assert runs[0].final_output.summary == "summary"

    # 6. Check other industry is empty
    assert len(store.get_successful_runs_by_industry(f"health-{uuid4().hex[:6]}")) == 0

def test_memory_store_get_successful_runs_by_industry():
    store = InMemoryStore()
    _test_store_get_successful_runs_by_industry(store)

@pytest.mark.skipif(
    not os.environ.get("POSTGRES_PASSWORD"),
    reason="POSTGRES_PASSWORD not set — skip live PostgresStore tests",
)
def test_postgres_store_get_successful_runs_by_industry():
    store = PostgresStore()
    try:
        _test_store_get_successful_runs_by_industry(store)
    finally:
        store.close()
