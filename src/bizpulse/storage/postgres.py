"""Postgres-backed Store. Drop-in replacement for InMemoryStore.

Uses `psycopg` (v3) with a connection pool. Same public method shape as
InMemoryStore so FastAPI / MCP / tests don't change. Swap is via the
`BIZPULSE_STORE` env var (see `bizpulse.storage.__init__`).

Schema mapping notes:
- `tenants.slug` is required (CITEXT UNIQUE in DB). The Pydantic Tenant
  model has it now too. New tenants get a slug from `slugify(name)` if
  the caller didn't pass one explicitly.
- `runs.output` JSONB ↔ Pydantic `RunRecord.final_output` (MarketingStrategy).
  We serialize/deserialize with model_dump_json / model_validate_json.
- `run_steps` (per-agent log) is its own table; we don't fully wire it here
  — Phase-6 LangGraph nodes will write to it as they execute.
- `agent_traces` field on RunRecord stays empty in this store (always read
  the live `run_steps` rows instead, in a follow-up).
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime
from typing import Iterable
from uuid import UUID, uuid4

from psycopg_pool import ConnectionPool

from bizpulse.logging import get_logger
from bizpulse.models import (
    Business,
    BusinessId,
    RunRecord,
    RunStatus,
    Tenant,
    TenantId,
    slugify,
)
from bizpulse.models.common import utcnow

log = get_logger(__name__)


def _generate_api_key() -> str:
    return f"bzp_{secrets.token_urlsafe(24)}"


def _build_dsn_from_env() -> str:
    return (
        f"host={os.environ['POSTGRES_HOST']} "
        f"port={os.environ['POSTGRES_PORT']} "
        f"dbname={os.environ['POSTGRES_DB']} "
        f"user={os.environ['POSTGRES_USER']} "
        f"password={os.environ['POSTGRES_PASSWORD']}"
    )


class PostgresStore:
    """Persistent store backed by the BizPulse Postgres schema."""

    def __init__(self, dsn: str | None = None, *, min_size: int = 1, max_size: int = 8) -> None:
        self.dsn = dsn or _build_dsn_from_env()
        self._pool = ConnectionPool(self.dsn, min_size=min_size, max_size=max_size, open=True)

    def close(self) -> None:
        self._pool.close()

    # ----- tenants -------------------------------------------------------

    def create_tenant(self, name: str, slug: str | None = None) -> Tenant:
        chosen_slug = slug or slugify(name)
        api_key = _generate_api_key()
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenants (name, slug, api_key) "
                "VALUES (%s, %s, %s) "
                "RETURNING id, name, slug, api_key, created_at",
                (name, chosen_slug, api_key),
            )
            row = cur.fetchone()
            assert row is not None
            tid, tname, tslug, takey, tcreated = row
        return Tenant(id=tid, name=tname, slug=tslug, api_key=takey, created_at=tcreated)

    def get_tenant(self, tenant_id: TenantId) -> Tenant | None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, slug, api_key, created_at FROM tenants WHERE id = %s",
                (str(tenant_id),),
            )
            row = cur.fetchone()
        return _row_to_tenant(row)

    def get_tenant_by_api_key(self, api_key: str) -> Tenant | None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, slug, api_key, created_at FROM tenants WHERE api_key = %s",
                (api_key,),
            )
            row = cur.fetchone()
        return _row_to_tenant(row)

    def list_tenants(self) -> list[Tenant]:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, slug, api_key, created_at FROM tenants ORDER BY created_at"
            )
            rows = cur.fetchall()
        return [t for t in (_row_to_tenant(r) for r in rows) if t is not None]

    # ----- businesses ----------------------------------------------------

    def create_business(
        self,
        tenant_id: TenantId,
        url: str,
        industry: str | None = None,
    ) -> Business:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO businesses (tenant_id, url, industry, status) "
                "VALUES (%s, %s, %s, 'pending') "
                "RETURNING id, tenant_id, url, industry, status, created_at",
                (str(tenant_id), url, industry),
            )
            row = cur.fetchone()
            assert row is not None
        return _row_to_business(row)

    def get_business(self, business_id: BusinessId) -> Business | None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, tenant_id, url, industry, status, created_at "
                "FROM businesses WHERE id = %s",
                (str(business_id),),
            )
            row = cur.fetchone()
        return _row_to_business(row) if row else None

    def list_businesses(self, tenant_id: TenantId) -> list[Business]:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, tenant_id, url, industry, status, created_at "
                "FROM businesses WHERE tenant_id = %s ORDER BY created_at",
                (str(tenant_id),),
            )
            rows = cur.fetchall()
        return [_row_to_business(r) for r in rows]

    # ----- runs ----------------------------------------------------------

    def create_run(self, tenant_id: TenantId, business_id: BusinessId) -> RunRecord:
        # Verify the business belongs to this tenant before writing the run.
        biz = self.get_business(business_id)
        if biz is None:
            raise KeyError(f"unknown business: {business_id}")
        if biz.tenant_id != tenant_id:
            raise ValueError("business belongs to a different tenant")
        run_id = uuid4()
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO runs (id, tenant_id, business_id, status) "
                "VALUES (%s, %s, %s, 'pending') "
                "RETURNING id, tenant_id, business_id, status, started_at, finished_at, error, output",
                (str(run_id), str(tenant_id), str(business_id)),
            )
            row = cur.fetchone()
            assert row is not None
        return _row_to_run(row)

    def get_run(self, run_id: UUID) -> RunRecord | None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, tenant_id, business_id, status, started_at, finished_at, error, output "
                "FROM runs WHERE id = %s",
                (str(run_id),),
            )
            row = cur.fetchone()
        return _row_to_run(row) if row else None

    def update_run_status(
        self,
        run_id: UUID,
        status: RunStatus,
        *,
        error: str | None = None,
    ) -> RunRecord:
        finished = utcnow() if status in {"complete", "failed"} else None
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE runs SET status = %s, error = %s, "
                "finished_at = COALESCE(%s, finished_at) "
                "WHERE id = %s "
                "RETURNING id, tenant_id, business_id, status, started_at, finished_at, error, output",
                (status, error, finished, str(run_id)),
            )
            row = cur.fetchone()
            if row is None:
                raise KeyError(f"unknown run: {run_id}")
        return _row_to_run(row)

    def count_runs_for_tenant_since(
        self, tenant_id: TenantId, since: datetime
    ) -> int:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM runs WHERE tenant_id = %s AND started_at >= %s",
                (str(tenant_id), since),
            )
            row = cur.fetchone()
        return int(row[0]) if row else 0

    def count_runs_for_tenant(self, tenant_id: TenantId) -> int:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM runs WHERE tenant_id = %s",
                (str(tenant_id),),
            )
            row = cur.fetchone()
        return int(row[0]) if row else 0

    def list_runs_for_business(self, business_id: BusinessId) -> list[RunRecord]:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, tenant_id, business_id, status, started_at, finished_at, error, output "
                "FROM runs WHERE business_id = %s ORDER BY started_at DESC",
                (str(business_id),),
            )
            rows = cur.fetchall()
        return [_row_to_run(r) for r in rows]

    # ----- diagnostics ---------------------------------------------------

    def stats(self) -> dict[str, int]:
        with self._pool.connection() as conn, conn.cursor() as cur:
            counts: dict[str, int] = {}
            for table in ("tenants", "businesses", "runs"):
                cur.execute(f"SELECT count(*) FROM {table}")
                row = cur.fetchone()
                counts[table] = int(row[0]) if row else 0
        return counts


# ----- row mappers ---------------------------------------------------------

def _row_to_tenant(row: Iterable | None) -> Tenant | None:
    if row is None:
        return None
    tid, name, slug, api_key, created_at = row
    return Tenant(id=tid, name=name, slug=slug, api_key=api_key, created_at=created_at)


def _row_to_business(row: Iterable) -> Business:
    bid, tid, url, industry, status, created_at = row
    return Business(
        id=bid,
        tenant_id=tid,
        url=url,
        industry=industry,
        status=status,
        created_at=created_at,
    )


def _row_to_run(row: Iterable) -> RunRecord:
    rid, tid, biz_id, status, started_at, finished_at, error, output = row
    final_output = None
    if output is not None:
        # output is JSONB; psycopg returns it as a parsed dict already.
        try:
            from bizpulse.models.strategy import MarketingStrategy
            final_output = MarketingStrategy.model_validate(output)
        except Exception:  # noqa: BLE001 — old-shape rows shouldn't crash GET /runs/{id}
            final_output = None
    return RunRecord(
        id=rid,
        tenant_id=tid,
        business_id=biz_id,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        error=error,
        agent_traces=[],
        final_output=final_output,
    )
