# Template Engine – Architecture & Roadmap

## Vision
A multi‑industry, AI‑native document engine where business users design templates by describing intent or dragging fields, never writing SQL. Integrates with n8n, Make.com, Zapier via a single stable API.

## Phases

### Phase 1 – Core Template Engine
- Block‑based editor, field palette, real‑data preview, pluggable renderers (HTML, DOCX, PDF, XLSX, Markdown).
- Database schema and API surface are final – no schema rework later.

### Phase 2 – Intent‑Driven + AI Prompt Placeholders
- eivs.intenttemplates mapping, LLM prompt placeholders, AI‑generated SQL via Safety Gate.

### Phase 3 – Advanced AI Design Tools
- Doc→template converter, AI layout/table designer, text polish/localization, anomaly checks.

### Phase 4 – Governance, Marketplace, Performance
- Workflow states (draft → review → approved → published), audit logs, marketplace packs, async rendering.

### Phase 5 – Ecosystem, Analytics & Differentiation
- Usage analytics, AI recommendations, SDKs, admin console, compliance controls.

## Key Principles
- **No SQL for business users** – fields come from semantic models.
- **Stable runtime API** – POST /v1/documents/generate is the only integration point.
- **AI‑native architecture** – all AI features designed in up front, added incrementally without schema changes.
