-- Migration 003: business reference documents (PDF / DOCX / TXT / etc.)
-- Uploaded by tenants alongside the URL crawl to enrich the analysis context.
-- Idempotent.

CREATE TABLE IF NOT EXISTS business_documents (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID         NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    business_id   UUID         NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    filename      TEXT         NOT NULL,
    content_type  TEXT         NOT NULL,
    size_bytes    INTEGER      NOT NULL,
    n_chunks      INTEGER      NOT NULL DEFAULT 0,
    sha256        TEXT         NOT NULL,
    extracted_chars INTEGER    NOT NULL DEFAULT 0,
    uploaded_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    notes         TEXT
);

CREATE INDEX IF NOT EXISTS business_documents_business_idx ON business_documents (business_id);
CREATE UNIQUE INDEX IF NOT EXISTS business_documents_dedup_idx ON business_documents (business_id, sha256);

COMMENT ON TABLE business_documents
    IS 'User-uploaded reference docs (policies, prior reports, brand guidelines). Their text gets chunked + embedded into the tenant Qdrant collection alongside the URL crawl, so the agents see them as additional context.';
