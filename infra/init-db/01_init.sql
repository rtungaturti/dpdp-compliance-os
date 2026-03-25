-- DPDP Compliance OS — Postgres Init
-- Runs on first start (docker-entrypoint-initdb.d)

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";          -- pgvector for RAG (Day 8)
CREATE EXTENSION IF NOT EXISTS "pg_trgm";         -- fuzzy search
CREATE EXTENSION IF NOT EXISTS "btree_gin";

-- ==========================================================================
-- DAY 1: Consent Engine
-- ==========================================================================
CREATE TABLE consent_records (
    consent_id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    principal_id        TEXT NOT NULL,
    data_fiduciary_id   TEXT NOT NULL,
    purpose_ids         TEXT[] NOT NULL,
    legal_basis         TEXT NOT NULL,
    data_categories     TEXT[] NOT NULL,
    retention_days      INT NOT NULL DEFAULT 365,
    is_child            BOOLEAN NOT NULL DEFAULT FALSE,
    guardian_consent_ref TEXT,
    status              TEXT NOT NULL DEFAULT 'active',
    granted_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    withdrawn_at        TIMESTAMPTZ,
    withdrawal_reason   TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_consent_principal ON consent_records (principal_id);
CREATE INDEX idx_consent_fiduciary ON consent_records (data_fiduciary_id);
CREATE INDEX idx_consent_status ON consent_records (status);
CREATE INDEX idx_consent_purpose ON consent_records USING GIN (purpose_ids);

-- Audit log (immutable — no updates allowed)
CREATE TABLE consent_audit_log (
    audit_id    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    consent_id  UUID REFERENCES consent_records (consent_id),
    action      TEXT NOT NULL,   -- GRANTED, WITHDRAWN, CHECKED, EXPIRED
    actor_id    TEXT,
    detail      JSONB NOT NULL DEFAULT '{}',
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ==========================================================================
-- DAY 1: Role Classifier
-- ==========================================================================
CREATE TABLE entity_classifications (
    classification_id   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id           TEXT NOT NULL,
    entity_name         TEXT NOT NULL,
    role                TEXT NOT NULL,
    is_sdf              BOOLEAN NOT NULL DEFAULT FALSE,
    sdf_triggers        TEXT[] NOT NULL DEFAULT '{}',
    risk_score          INT NOT NULL DEFAULT 0,
    classified_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at          TIMESTAMPTZ,
    metadata            JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX idx_entity_id ON entity_classifications (entity_id);
CREATE INDEX idx_entity_role ON entity_classifications (role);

-- ==========================================================================
-- DAY 1: Rights Portal
-- ==========================================================================
CREATE TYPE rights_request_type AS ENUM (
    'access', 'correction', 'erasure', 'portability',
    'object', 'restrict_processing', 'nomination'
);

CREATE TYPE rights_request_status AS ENUM (
    'submitted', 'identity_verified', 'in_review',
    'hitl_review', 'approved', 'rejected', 'completed', 'expired'
);

CREATE TABLE rights_requests (
    request_id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    principal_id        TEXT NOT NULL,
    request_type        rights_request_type NOT NULL,
    status              rights_request_status NOT NULL DEFAULT 'submitted',
    data_fiduciary_id   TEXT NOT NULL,
    description         TEXT,
    submitted_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    identity_verified_at TIMESTAMPTZ,
    due_at              TIMESTAMPTZ NOT NULL,   -- 30 days per DPDP §11
    completed_at        TIMESTAMPTZ,
    temporal_workflow_id TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX idx_rights_principal ON rights_requests (principal_id);
CREATE INDEX idx_rights_status ON rights_requests (status);
CREATE INDEX idx_rights_due ON rights_requests (due_at) WHERE status != 'completed';

-- ==========================================================================
-- DAY 1: Evidence Generator
-- ==========================================================================
CREATE TABLE evidence_binders (
    binder_id       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    binder_type     TEXT NOT NULL,   -- audit, breach, dpia, rights_response
    reference_id    UUID,
    s3_key          TEXT,
    checksum        TEXT,
    generated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    generated_by    TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}'
);

-- ==========================================================================
-- Helper: auto-update updated_at
-- ==========================================================================
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_consent_updated_at
    BEFORE UPDATE ON consent_records
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
