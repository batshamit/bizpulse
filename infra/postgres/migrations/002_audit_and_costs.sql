-- Migration 002: admin audit log + per-run cost / token columns
-- Idempotent. Run via scripts/migrate_postgres.sh.

-- Per-run usage stats — populated by runner_service after the LangGraph
-- completes. Aggregated at the tenant level via SUM() in admin queries.
ALTER TABLE runs
    ADD COLUMN IF NOT EXISTS total_input_tokens  BIGINT          NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS total_output_tokens BIGINT          NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS total_cost_usd      NUMERIC(12, 6)  NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS llm_call_count      INTEGER         NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS runs_tenant_started_idx ON runs (tenant_id, started_at DESC);

-- Admin audit log — every PATCH / suspend / impersonate / delete by an
-- operator is recorded here. Append-only. Older entries can be archived
-- but we do NOT support DELETE on this table from the application layer.
CREATE TABLE IF NOT EXISTS admin_audit_log (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    occurred_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    actor       TEXT         NOT NULL,        -- 'admin' (shared key) or future user id
    action      TEXT         NOT NULL,        -- 'tenant.update', 'tenant.impersonate', 'tenant.delete', 'tenant.cleanup', 'admin.login'
    target_kind TEXT,                          -- 'tenant', 'run', NULL for system events
    target_id   TEXT,                          -- UUID or pattern; TEXT to allow non-UUID targets
    details     JSONB        NOT NULL DEFAULT '{}'::jsonb,
    request_ip  TEXT
);

CREATE INDEX IF NOT EXISTS admin_audit_log_occurred_at_idx ON admin_audit_log (occurred_at DESC);
CREATE INDEX IF NOT EXISTS admin_audit_log_action_idx     ON admin_audit_log (action);
CREATE INDEX IF NOT EXISTS admin_audit_log_target_idx     ON admin_audit_log (target_kind, target_id);

COMMENT ON TABLE  admin_audit_log
    IS 'Append-only audit trail of admin/operator actions. Never delete from app code.';
COMMENT ON COLUMN runs.total_cost_usd
    IS 'Sum of council_result.cost_usd across every LLM call in this run. NUMERIC(12,6) ~ $1M with 6dp.';
