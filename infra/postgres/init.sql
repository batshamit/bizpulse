-- BizPulse — Postgres schema bootstrap
-- Runs once on a fresh data volume (or apply manually to an existing instance).

CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- for gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "citext";

-- ---------- Tenancy ----------

CREATE TABLE IF NOT EXISTS tenants (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT         NOT NULL,
    slug        CITEXT       NOT NULL UNIQUE,
    api_key     TEXT         NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS tenants_slug_idx ON tenants (slug);

-- ---------- Businesses (one tenant has many) ----------

CREATE TABLE IF NOT EXISTS businesses (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID         NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    url         TEXT         NOT NULL,
    industry    TEXT,
    status      TEXT         NOT NULL DEFAULT 'pending',  -- pending|crawling|indexed|ready|failed
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS businesses_tenant_idx ON businesses (tenant_id);
CREATE INDEX IF NOT EXISTS businesses_status_idx ON businesses (status);

-- ---------- Pipeline runs (audit log of every analysis attempt) ----------

CREATE TABLE IF NOT EXISTS runs (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id   UUID         NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    tenant_id     UUID         NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    status        TEXT         NOT NULL DEFAULT 'started',  -- started|crawling|reasoning|done|failed
    started_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    error         TEXT,
    output        JSONB
);

CREATE INDEX IF NOT EXISTS runs_business_idx ON runs (business_id);
CREATE INDEX IF NOT EXISTS runs_tenant_idx   ON runs (tenant_id);
CREATE INDEX IF NOT EXISTS runs_status_idx   ON runs (status);

-- ---------- Per-step agent logs (debug + replay) ----------

CREATE TABLE IF NOT EXISTS run_steps (
    id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id       UUID         NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    agent        TEXT         NOT NULL,           -- orchestrator|brand|audience|competitor|content|strategist|critic
    attempt      INT          NOT NULL DEFAULT 1,
    started_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    input        JSONB,
    output       JSONB,
    error        TEXT,
    chunk_ids    TEXT[]                            -- citations referenced
);

CREATE INDEX IF NOT EXISTS run_steps_run_idx ON run_steps (run_id);

-- ---------- Demo seed: a single tenant for local dev ----------

INSERT INTO tenants (name, slug, api_key)
VALUES ('Demo Tenant', 'demo', 'dev-demo-key-rotate-me')
ON CONFLICT (slug) DO NOTHING;
