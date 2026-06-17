-- =====================================================================
-- complete.sql - Template Builder DDL (all phases)
-- =====================================================================
-- =====================================================================
--  These aer temporary table created so that we can build the template Builder we need
-- remove this tables in the actual production as these tables will be there
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS eivs;

CREATE TABLE IF NOT EXISTS eivs.intents (
    intent_id      SERIAL PRIMARY KEY,
    intent_code    TEXT UNIQUE NOT NULL,     -- e.g. REQUEST_LOAN_NOC
    display_name   TEXT NOT NULL,
    description    TEXT,
	category       TEXT,
    is_active      BOOLEAN NOT NULL DEFAULT TRUE
);

-- 1) Datasources table – map logical names to Adapter/datasource middleware
CREATE TABLE IF NOT EXISTS eivs.datasources (
    datasource_id SERIAL PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,   -- e.g. CRM_DB, LOAN_CORE_DB
    datasource_type TEXT NOT NULL,          -- 'postgres', 'snowflake', 'api', etc.
    connection_key TEXT NOT NULL,         -- what Adapter/middleware uses to route
    description   TEXT,
    semantic_model_yaml TEXT,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE
);

-- Insert intent
INSERT INTO eivs.intents (intent_code, display_name, description, is_active)
VALUES ('REQUEST_LOAN_NOC', 'Loan NOC Request', 'Customer has closed a loan and requests a NOC.', TRUE);

INSERT INTO eivs.datasources (name, datasource_type, connection_key, description, is_active)
VALUES
('CRM_DB',       'postgres', 'postgresql://eivsdemo:eivsdemo@kasetti-db:5432/kasetti_bank', 'CRM customer schema in kasetti_bank',         TRUE),
('LOAN_CORE_DB', 'postgres', 'postgresql://eivsdemo:eivsdemo@kasetti-db:5432/kasetti_bank', 'Loan core schema in kasetti_bank',             TRUE),
('FIN_DB',       'postgres', 'postgresql://eivsdemo:eivsdemo@kasetti-db:5432/kasetti_bank', 'Finance and invoicing schema in kasetti_bank', TRUE),
('HEALTH_DB',    'postgres', 'postgresql://eivsdemo:eivsdemo@kasetti-db:5432/kasetti_bank', 'Healthcare EMR schema in kasetti_bank',        TRUE),
('INSURANCE_DB', 'postgres', 'postgresql://eivsdemo:eivsdemo@kasetti-db:5432/kasetti_bank', 'Insurance policies schema in kasetti_bank',    TRUE),
('MFG_DB',       'postgres', 'postgresql://eivsdemo:eivsdemo@kasetti-db:5432/kasetti_bank', 'Manufacturing schema in kasetti_bank',         TRUE);


-- Assuming PostgreSQL
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE SCHEMA IF NOT EXISTS template_builder;

-- ---------------------------------------------------------------------
-- Templates
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS template_builder.templates (
  template_id       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name              TEXT NOT NULL,
  description       TEXT,
  status            TEXT NOT NULL CHECK (status IN ('draft','published','archived','in_review','approved')),
  output_target     TEXT NOT NULL CHECK (output_target IN ('html','docx','pdf','xlsx','md')),
  layout_json       JSONB NOT NULL,
  default_locale    TEXT NOT NULL DEFAULT 'en',
  supported_locales TEXT[] NOT NULL DEFAULT ARRAY['en'],
  industry          TEXT,
  tags              TEXT[],
  created_by        TEXT NOT NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_templates_status
  ON template_builder.templates (status);

CREATE INDEX IF NOT EXISTS idx_templates_industry
  ON template_builder.templates (industry);

CREATE INDEX IF NOT EXISTS idx_templates_tags
  ON template_builder.templates USING GIN (tags);

-- ---------------------------------------------------------------------
-- Template versions (immutable snapshots)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS template_builder.template_versions (
  version_id     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  template_id    UUID NOT NULL REFERENCES template_builder.templates(template_id) ON DELETE CASCADE,
  version_number INT  NOT NULL,
  layout_json    JSONB NOT NULL,
  output_target  TEXT NOT NULL CHECK (output_target IN ('html','docx','pdf','xlsx','md')),
  change_summary TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (template_id, version_number)
);

CREATE INDEX IF NOT EXISTS idx_template_versions_template
  ON template_builder.template_versions (template_id);

-- ---------------------------------------------------------------------
-- Global placeholder registry
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS template_builder.placeholders_registry (
  registry_id     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name            TEXT NOT NULL,
  description     TEXT,
  generation_mode TEXT NOT NULL CHECK (generation_mode IN ('manual_sql','llm_prompt')),
  prompt          TEXT,
  sql_text        TEXT,
  datasource_id   INT NOT NULL REFERENCES eivs.datasources(datasource_id),
  value_type      TEXT NOT NULL DEFAULT 'string',
  cardinality     TEXT NOT NULL DEFAULT 'scalar' CHECK (cardinality IN ('scalar','list','table','json')),
  classification  TEXT NOT NULL DEFAULT 'internal',
  format_json     JSONB,
  sample_value    TEXT,
  metadata        JSONB,
  created_by      TEXT NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  is_active       BOOLEAN NOT NULL DEFAULT TRUE,
  UNIQUE (name)
);

CREATE INDEX IF NOT EXISTS idx_placeholders_datasource
  ON template_builder.placeholders_registry (datasource_id);

-- ---------------------------------------------------------------------
-- Template-specific placeholder bindings
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS template_builder.template_placeholders (
  template_placeholder_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  template_id        UUID NOT NULL REFERENCES template_builder.templates(template_id) ON DELETE CASCADE,
  registry_id        UUID NOT NULL REFERENCES template_builder.placeholders_registry(registry_id),
  override_prompt    TEXT,
  override_sql_text  TEXT,
  override_format    JSONB,
  override_datasource_id INT REFERENCES eivs.datasources(datasource_id),
  override_sample_value  TEXT,
  metadata           JSONB,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (template_id, registry_id)
);

CREATE INDEX IF NOT EXISTS idx_template_placeholders_template
  ON template_builder.template_placeholders (template_id);

CREATE INDEX IF NOT EXISTS idx_template_placeholders_registry
  ON template_builder.template_placeholders (registry_id);

-- ---------------------------------------------------------------------
-- Render jobs
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS template_builder.render_jobs (
  job_id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  template_id     UUID NOT NULL REFERENCES template_builder.templates(template_id),
  version_id      UUID REFERENCES template_builder.template_versions(version_id),
  status          TEXT NOT NULL CHECK (status IN ('queued','running','success','error')),
  output_target   TEXT NOT NULL CHECK (output_target IN ('html','docx','pdf','xlsx','md')),
  locale          TEXT NOT NULL,
  runtime_params  JSONB,
  result_location TEXT,
  logs            TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_render_jobs_template
  ON template_builder.render_jobs (template_id);

CREATE INDEX IF NOT EXISTS idx_render_jobs_status
  ON template_builder.render_jobs (status);

-- =====================================================================
-- INTENT MAPPING (PHASE 2)
-- =====================================================================

CREATE TABLE IF NOT EXISTS eivs.intent_templates (
  intent_id    INT  NOT NULL REFERENCES eivs.intents(intent_id),
  template_id  UUID NOT NULL REFERENCES template_builder.templates(template_id),
  is_primary   BOOLEAN NOT NULL DEFAULT FALSE,
  rank         INT NOT NULL DEFAULT 1,
  PRIMARY KEY (intent_id, template_id)
);

CREATE INDEX IF NOT EXISTS idx_intent_templates_intent
  ON eivs.intent_templates (intent_id);

-- =====================================================================
-- AI DESIGN TABLES (PHASE 3)
-- =====================================================================

CREATE TABLE IF NOT EXISTS template_builder.uploaded_documents (
  upload_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  template_id       UUID REFERENCES template_builder.templates(template_id),
  original_filename TEXT NOT NULL,
  mime_type         TEXT NOT NULL,
  storage_uri       TEXT NOT NULL,
  extraction_status TEXT NOT NULL CHECK (extraction_status IN ('pending','success','failed')),
  extracted_layout  JSONB,
  extraction_errors JSONB,
  created_by        TEXT NOT NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_uploaded_documents_template
  ON template_builder.uploaded_documents (template_id);

CREATE TABLE IF NOT EXISTS template_builder.ai_suggestions (
  suggestion_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  template_id   UUID REFERENCES template_builder.templates(template_id),
  scope         TEXT NOT NULL CHECK (scope IN ('layout','table','text','anomaly')),
  input_context JSONB NOT NULL,
  suggested_json JSONB NOT NULL,
  status        TEXT NOT NULL CHECK (status IN ('pending','accepted','rejected')),
  created_by    TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  decided_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_ai_suggestions_template
  ON template_builder.ai_suggestions (template_id);

CREATE INDEX IF NOT EXISTS idx_ai_suggestions_scope
  ON template_builder.ai_suggestions (scope);

-- =====================================================================
-- GOVERNANCE, AUDIT, TESTS, MARKETPLACE (PHASE 4)
-- =====================================================================

CREATE TABLE IF NOT EXISTS template_builder.audit_events (
    event_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type TEXT NOT NULL,
    entity_id UUID NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    summary TEXT,
    details_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_audit_events_entity ON template_builder.audit_events (entity_type, entity_id);
CREATE INDEX idx_audit_events_actor ON template_builder.audit_events (actor);

CREATE TABLE IF NOT EXISTS template_builder.template_tests (
  test_id        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  template_id    UUID NOT NULL REFERENCES template_builder.templates(template_id) ON DELETE CASCADE,
  name           TEXT NOT NULL,
  description    TEXT,
  runtime_params JSONB NOT NULL,
  expected_checks JSONB,
  created_by     TEXT NOT NULL,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_template_tests_template
  ON template_builder.template_tests (template_id);

CREATE TABLE IF NOT EXISTS template_builder.blocks_library (
  block_id      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name          TEXT NOT NULL,
  description   TEXT,
  block_json    JSONB NOT NULL,
  industry      TEXT,
  tags          TEXT[],
  created_by    TEXT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_blocks_library_industry
  ON template_builder.blocks_library (industry);

CREATE INDEX IF NOT EXISTS idx_blocks_library_tags
  ON template_builder.blocks_library USING GIN (tags);

-- Marketplace items — payload stores source data for import fallback
CREATE TABLE IF NOT EXISTS template_builder.marketplace_items (
  item_id     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  type        TEXT NOT NULL CHECK (type IN ('template','block','placeholder')),
  source_id   UUID NOT NULL,
  name        TEXT NOT NULL,
  description TEXT,
  owner       TEXT NOT NULL,
  license     TEXT DEFAULT 'Community',
  rating      NUMERIC(2,1),
  downloads   INT DEFAULT 0,
  tags        TEXT[],
  is_public   BOOLEAN NOT NULL DEFAULT TRUE,
  payload     JSONB,           -- stores source data so import works even after source deletion
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_marketplace_items_type
  ON template_builder.marketplace_items (type);

CREATE INDEX IF NOT EXISTS idx_marketplace_items_tags
  ON template_builder.marketplace_items USING GIN (tags);

CREATE TABLE IF NOT EXISTS template_builder.logical_models (
  model_id        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name            TEXT NOT NULL UNIQUE,
  definition_json JSONB NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =====================================================================
-- OPTIONAL ANALYTICS / STATS (PHASE 5)
-- =====================================================================

CREATE TABLE IF NOT EXISTS template_builder.template_usage_stats (
  template_id           UUID PRIMARY KEY REFERENCES template_builder.templates(template_id) ON DELETE CASCADE,
  total_renders         BIGINT NOT NULL DEFAULT 0,
  last_rendered_at      TIMESTAMPTZ,
  last_error_at         TIMESTAMPTZ,
  last_error_message    TEXT
);

CREATE TABLE IF NOT EXISTS template_builder.placeholder_usage_stats (
  registry_id           UUID PRIMARY KEY REFERENCES template_builder.placeholders_registry(registry_id) ON DELETE CASCADE,
  total_resolutions     BIGINT NOT NULL DEFAULT 0,
  last_resolved_at      TIMESTAMPTZ,
  last_error_at         TIMESTAMPTZ,
  last_error_message    TEXT
);

-- =====================================================================
-- END OF DDL
-- =====================================================================