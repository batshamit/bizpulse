-- Migration 001: admin / per-tenant override columns
-- Idempotent — safe to re-apply. Run via scripts/migrate_postgres.sh.

ALTER TABLE tenants
    ADD COLUMN IF NOT EXISTS daily_limit_override INTEGER,
    ADD COLUMN IF NOT EXISTS suspended            BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS suspended_at         TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS notes                TEXT;

COMMENT ON COLUMN tenants.daily_limit_override
    IS 'Per-tenant override of BIZPULSE_DAILY_ANALYSIS_LIMIT. NULL = use the global env value.';
COMMENT ON COLUMN tenants.suspended
    IS 'When true, POST /analyze returns 403 for this tenant regardless of quota.';

CREATE INDEX IF NOT EXISTS tenants_suspended_idx ON tenants (suspended);
