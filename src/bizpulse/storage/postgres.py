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
from collections.abc import Iterable
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from psycopg_pool import ConnectionPool

from bizpulse.logging import get_logger
from bizpulse.models import (
    Business,
    BusinessId,
    DailyResearchReport,
    MarketingStrategy,
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

    def create_tenant(self, name: str, slug: str | None = None, is_test: bool = False) -> Tenant:
        chosen_slug = slug or slugify(name)
        api_key = _generate_api_key()
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenants (name, slug, api_key, is_test) "
                "VALUES (%s, %s, %s, %s) "
                "RETURNING id, name, slug, api_key, created_at, "
                "         daily_limit_override, suspended, notes, is_test",
                (name, chosen_slug, api_key, is_test),
            )
            row = cur.fetchone()
            assert row is not None
        result = _row_to_tenant(row)
        assert result is not None
        return result

    def update_tenant(
        self,
        tenant_id: TenantId,
        *,
        name: str | None = None,
        daily_limit_override: int | None = None,
        clear_daily_limit_override: bool = False,
        suspended: bool | None = None,
        notes: str | None = None,
        is_test: bool | None = None,
    ) -> Tenant | None:
        """Admin-only updater. Pass `clear_daily_limit_override=True` to
        explicitly NULL the column (since None means 'don't change')."""
        sets: list[str] = []
        args: list[object] = []
        if name is not None:
            sets.append("name = %s")
            args.append(name)
        if clear_daily_limit_override:
            sets.append("daily_limit_override = NULL")
        elif daily_limit_override is not None:
            sets.append("daily_limit_override = %s")
            args.append(daily_limit_override)
        if suspended is not None:
            sets.append("suspended = %s")
            args.append(suspended)
            if suspended:
                sets.append("suspended_at = now()")
            else:
                sets.append("suspended_at = NULL")
        if notes is not None:
            sets.append("notes = %s")
            args.append(notes)
        if is_test is not None:
            sets.append("is_test = %s")
            args.append(is_test)

        if not sets:
            return self.get_tenant(tenant_id)

        args.append(str(tenant_id))
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"UPDATE tenants SET {', '.join(sets)} WHERE id = %s "
                "RETURNING id, name, slug, api_key, created_at, "
                "         daily_limit_override, suspended, notes, is_test",
                args,
            )
            row = cur.fetchone()
        return _row_to_tenant(row)

    def get_tenant(self, tenant_id: TenantId) -> Tenant | None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, slug, api_key, created_at, daily_limit_override, suspended, notes, is_test "
                "FROM tenants WHERE id = %s",
                (str(tenant_id),),
            )
            row = cur.fetchone()
        return _row_to_tenant(row)

    def get_tenant_by_api_key(self, api_key: str) -> Tenant | None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, slug, api_key, created_at, daily_limit_override, suspended, notes, is_test "
                "FROM tenants WHERE api_key = %s",
                (api_key,),
            )
            row = cur.fetchone()
        return _row_to_tenant(row)

    def list_tenants(self) -> list[Tenant]:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, slug, api_key, created_at, daily_limit_override, suspended, notes, is_test "
                "FROM tenants ORDER BY created_at"
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

    def create_run(
        self,
        tenant_id: TenantId,
        business_id: BusinessId,
        run_type: str = "marketing_strategy",
        inputs: dict | None = None,
    ) -> RunRecord:
        # Verify the business belongs to this tenant before writing the run.
        biz = self.get_business(business_id)
        if biz is None:
            raise KeyError(f"unknown business: {business_id}")
        if biz.tenant_id != tenant_id:
            raise ValueError("business belongs to a different tenant")
        run_id = uuid4()
        import json
        import socket
        import os

        hostname = socket.gethostname()
        pid = os.getpid()
        now_str = utcnow().isoformat()

        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO runs (id, tenant_id, business_id, status, output) "
                "VALUES (%s, %s, %s, 'pending', %s::jsonb) "
                "RETURNING id, tenant_id, business_id, status, started_at, finished_at, error, output, "
                "          total_input_tokens, total_output_tokens, total_cost_usd, llm_call_count",
                (
                    str(run_id),
                    str(tenant_id),
                    str(business_id),
                    json.dumps({
                        "run_type": run_type,
                        "inputs": inputs,
                        "hostname": hostname,
                        "pid": pid,
                        "last_heartbeat_at": now_str,
                    })
                ),
            )
            row = cur.fetchone()
            assert row is not None
        return _row_to_run(row)

    def delete_run(self, run_id: UUID) -> bool:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM runs WHERE id = %s", (str(run_id),))
            return cur.rowcount > 0

    def get_run(self, run_id: UUID) -> RunRecord | None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, tenant_id, business_id, status, started_at, finished_at, error, output, "
                "       total_input_tokens, total_output_tokens, total_cost_usd, llm_call_count "
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
                "RETURNING id, tenant_id, business_id, status, started_at, finished_at, error, output, "
                "          total_input_tokens, total_output_tokens, total_cost_usd, llm_call_count",
                (status, error, finished, str(run_id)),
            )
            row = cur.fetchone()
            if row is None:
                raise KeyError(f"unknown run: {run_id}")
        return _row_to_run(row)

    def add_agent_trace(self, run_id: UUID, status: RunStatus, trace: object) -> None:
        """Append an AgentTrace to the output jsonb column in Postgres, and update the run's status in real-time."""
        import json
        with self._pool.connection() as conn, conn.cursor() as cur:
            # 1. Fetch current output
            cur.execute("SELECT output FROM runs WHERE id = %s", (str(run_id),))
            row = cur.fetchone()
            if not row:
                return
            output = row[0] or {}
            # Ensure it is a dict
            if not isinstance(output, dict):
                try:
                    output = json.loads(output)
                except Exception:
                    output = {}
            
            # 2. Append trace
            traces = output.setdefault("agent_traces", [])
            # Append new trace (remove existing duplicate if present by agent name)
            traces = [t for t in traces if t.get("agent") != trace.agent]
            # Use model_dump_json or dict representation of Pydantic model
            if hasattr(trace, "model_dump_json"):
                traces.append(json.loads(trace.model_dump_json()))
            elif hasattr(trace, "dict"):
                traces.append(json.loads(json.dumps(trace.dict(), default=str)))
            else:
                traces.append(trace)
            output["agent_traces"] = traces
            
            # 3. Save back
            cur.execute(
                "UPDATE runs SET status = %s, output = %s::jsonb WHERE id = %s",
                (status, json.dumps(output), str(run_id))
            )

    def usage_for_tenant(self, tenant_id: TenantId) -> dict[str, float | int]:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(SUM(total_cost_usd), 0)::float, "
                "       COALESCE(SUM(total_input_tokens), 0)::bigint, "
                "       COALESCE(SUM(total_output_tokens), 0)::bigint, "
                "       COALESCE(SUM(llm_call_count), 0)::int "
                "FROM runs WHERE tenant_id = %s",
                (str(tenant_id),),
            )
            row = cur.fetchone() or (0.0, 0, 0, 0)
        return {
            "total_cost_usd": float(row[0] or 0.0),
            "total_input_tokens": int(row[1] or 0),
            "total_output_tokens": int(row[2] or 0),
            "llm_call_count": int(row[3] or 0),
        }

    def update_run_usage(
        self,
        run_id: UUID,
        *,
        cost_usd: float,
        input_tokens: int,
        output_tokens: int,
        llm_calls: int,
    ) -> None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE runs SET total_cost_usd = %s, total_input_tokens = %s, "
                "                total_output_tokens = %s, llm_call_count = %s "
                "WHERE id = %s",
                (cost_usd, input_tokens, output_tokens, llm_calls, str(run_id)),
            )

    def delete_tenant(self, tenant_id: TenantId) -> bool:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM tenants WHERE id = %s", (str(tenant_id),))
            return cur.rowcount > 0

    def find_tenants_by_name_regex(self, pattern: str) -> list[dict]:
        # Postgres POSIX regex with `~` operator. We don't pre-validate the
        # pattern in Python — let PG raise; the API returns the error.
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id::text, name, slug FROM tenants WHERE name ~ %s " "ORDER BY created_at",
                (pattern,),
            )
            return [{"id": r[0], "name": r[1], "slug": r[2]} for r in cur.fetchall()]

    def delete_tenants_by_name_regex(self, pattern: str) -> list[dict]:
        targets = self.find_tenants_by_name_regex(pattern)
        if not targets:
            return []
        ids = [t["id"] for t in targets]
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM tenants WHERE id::text = ANY(%s)", (ids,))
        return targets

    def insert_audit(self, **kw) -> UUID:
        import json

        details = kw.get("details") or {}
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO admin_audit_log "
                "  (actor, action, target_kind, target_id, details, request_ip) "
                "VALUES (%s, %s, %s, %s, %s::jsonb, %s) "
                "RETURNING id",
                (
                    kw.get("actor", ""),
                    kw.get("action", ""),
                    kw.get("target_kind"),
                    kw.get("target_id"),
                    json.dumps(details),
                    kw.get("request_ip"),
                ),
            )
            row = cur.fetchone()
        return row[0] if row else UUID(int=0)

    def list_audit(self, *, limit: int = 100, offset: int = 0) -> list[dict]:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id::text, occurred_at, actor, action, target_kind, "
                "       target_id, details, request_ip "
                "FROM admin_audit_log "
                "ORDER BY occurred_at DESC LIMIT %s OFFSET %s",
                (limit, offset),
            )
            rows = cur.fetchall()
        out = []
        for r in rows:
            out.append(
                {
                    "id": r[0],
                    "occurred_at": r[1].isoformat() if r[1] else None,
                    "actor": r[2],
                    "action": r[3],
                    "target_kind": r[4],
                    "target_id": r[5],
                    "details": r[6] or {},
                    "request_ip": r[7],
                }
            )
        return out

    def count_runs_for_tenant_since(self, tenant_id: TenantId, since: datetime) -> int:
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
                "SELECT id, tenant_id, business_id, status, started_at, finished_at, error, output, "
                "       total_input_tokens, total_output_tokens, total_cost_usd, llm_call_count "
                "FROM runs WHERE business_id = %s ORDER BY started_at DESC",
                (str(business_id),),
            )
            rows = cur.fetchall()
        return [_row_to_run(r) for r in rows]

    def get_successful_runs_by_industry(self, industry: str, limit: int = 3) -> list[RunRecord]:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT runs.id, runs.tenant_id, runs.business_id, runs.status, runs.started_at, runs.finished_at, "
                "       runs.error, runs.output, runs.total_input_tokens, runs.total_output_tokens, "
                "       runs.total_cost_usd, runs.llm_call_count "
                "FROM runs "
                "JOIN businesses ON runs.business_id = businesses.id "
                "WHERE businesses.industry = %s AND runs.status = 'complete' "
                "ORDER BY runs.finished_at DESC LIMIT %s",
                (industry, limit),
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

    def fail_orphaned_runs(self) -> int:
        """Find any runs that are currently in a non-terminal state and mark them as failed."""
        import socket
        from datetime import timedelta
        
        current_hostname = socket.gethostname()
        cutoff = utcnow() - timedelta(minutes=2)
        cutoff_str = cutoff.isoformat()
        
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE runs SET status = 'failed', error = 'Run aborted due to server restart/reload', "
                "finished_at = now() "
                "WHERE status NOT IN ('complete', 'failed') "
                "AND ( "
                "    output->>'hostname' = %s "
                "    OR output->>'last_heartbeat_at' IS NULL "
                "    OR (output->>'last_heartbeat_at')::timestamp with time zone < %s::timestamp with time zone "
                ")",
                (current_hostname, cutoff_str),
            )
            return cur.rowcount

    def heartbeat_run(self, run_id: UUID, hostname: str, pid: int) -> None:
        import json
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT output FROM runs WHERE id = %s", (str(run_id),))
            row = cur.fetchone()
            if not row:
                return
            output = row[0] or {}
            if not isinstance(output, dict):
                try:
                    output = json.loads(output)
                except Exception:
                    output = {}
            output["hostname"] = hostname
            output["pid"] = pid
            output["last_heartbeat_at"] = utcnow().isoformat()
            cur.execute(
                "UPDATE runs SET output = %s::jsonb WHERE id = %s",
                (json.dumps(output), str(run_id))
            )


# ----- row mappers ---------------------------------------------------------


def _row_to_tenant(row: Iterable | None) -> Tenant | None:
    if row is None:
        return None
    # Backward-compat row shapes: 5, 8, or 9 columns
    cols = list(row)
    tid, name, slug, api_key, created_at = cols[:5]
    daily_limit_override: int | None = None
    suspended: bool = False
    notes: str | None = None
    is_test: bool = False
    if len(cols) >= 9:
        daily_limit_override = cols[5]
        suspended = bool(cols[6])
        notes = cols[7]
        is_test = bool(cols[8])
    elif len(cols) >= 8:
        daily_limit_override = cols[5]
        suspended = bool(cols[6])
        notes = cols[7]
    return Tenant(
        id=tid,
        name=name,
        slug=slug,
        api_key=api_key,
        created_at=created_at,
        daily_limit_override=daily_limit_override,
        suspended=suspended,
        notes=notes,
        is_test=is_test,
    )


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
    cols = list(row)
    rid, tid, biz_id, status, started_at, finished_at, error, output = cols[:8]
    # Optional cost/token columns — present after migration 002.
    total_input = int(cols[8]) if len(cols) > 8 and cols[8] is not None else 0
    total_output = int(cols[9]) if len(cols) > 9 and cols[9] is not None else 0
    total_cost = float(cols[10]) if len(cols) > 10 and cols[10] is not None else 0.0
    llm_calls = int(cols[11]) if len(cols) > 11 and cols[11] is not None else 0
    final_output: MarketingStrategy | DailyResearchReport | None = None
    agent_traces = []
    run_type: Literal["marketing_strategy", "daily_research"] = "marketing_strategy"
    inputs = None
    hostname = None
    pid = None
    last_heartbeat_at = None
    if output is not None:
        inputs = output.get("inputs")
        val = output.get("run_type", "marketing_strategy")
        run_type = "daily_research" if val == "daily_research" else "marketing_strategy"
        hostname = output.get("hostname")
        pid = output.get("pid")
        lh_str = output.get("last_heartbeat_at")
        if lh_str:
            from datetime import datetime
            try:
                last_heartbeat_at = datetime.fromisoformat(lh_str)
            except Exception:
                pass
        if len(output) > 1:
            try:
                if run_type == "daily_research":
                    final_output = DailyResearchReport.model_validate(output)
                else:
                    final_output = MarketingStrategy.model_validate(output)

                if final_output and final_output.agent_traces:
                    agent_traces = final_output.agent_traces
            except Exception:
                final_output = None
    return RunRecord(
        id=rid,
        tenant_id=tid,
        business_id=biz_id,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        error=error,
        agent_traces=agent_traces,
        final_output=final_output,
        run_type=run_type,
        inputs=inputs,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        total_cost_usd=total_cost,
        llm_call_count=llm_calls,
        hostname=hostname,
        pid=pid,
        last_heartbeat_at=last_heartbeat_at,
    )
