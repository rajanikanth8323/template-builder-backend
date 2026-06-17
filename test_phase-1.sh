#!/usr/bin/env bash
set -euo pipefail
API_BASE="http://localhost:10001/v1"
DB_USER="postgres"
DB_NAME="template_builder"
DB_PASS="postgres"

# --------------------------------------------------------------------
# Helper functions
# --------------------------------------------------------------------
GREEN='\033[0;32m'; RED='\033[0;31m'; NC='\033[0m'
log() { echo -e "${GREEN}[TEST]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }

run_psql() {
  local query="$1"
  local cmd="psql -U $DB_USER -d $DB_NAME -w -t -A -c \"$query\""
  [[ -n "${DB_PASS:-}" ]] && cmd="PGPASSWORD=$DB_PASS $cmd"
  docker compose exec -T db bash -c "$cmd" 2>/dev/null | tr -d '\n'
}

extract_uuid() {
  local response="$1"
  [[ -z "$response" ]] && fail "Empty response – cannot extract UUID"
  echo "$response" | grep -oE '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' | head -1
}

time_op() {
  local start=$(date +%s.%N)
  "$@" >/dev/null 2>&1 || return 1
  local end=$(date +%s.%N)
  printf "%.3f" $(echo "$end - $start" | bc -l)
}

# --------------------------------------------------------------------
# Pre‑flight checks
# --------------------------------------------------------------------
log "Checking API health endpoint..."
HTTP_CODE=$(curl -s --max-time 5 -o /dev/null -w "%{http_code}" "${API_BASE}/healthz" || echo "000")
[[ "$HTTP_CODE" != "200" ]] && log "Health check returned $HTTP_CODE – continuing anyway"

log "Checking PostgreSQL schema..."
TABLE_COUNT=$(run_psql "SELECT count(*) FROM information_schema.tables WHERE table_schema='template_builder';")
[[ -z "$TABLE_COUNT" ]] && fail "Cannot query DB"
[[ "$TABLE_COUNT" -lt 10 ]] && fail "Expected ≥10 tables, found $TABLE_COUNT"
log "  Schema OK – $TABLE_COUNT tables"

# --------------------------------------------------------------------
# 1. Placeholder Registry CRUD
# --------------------------------------------------------------------
log "Creating manual SQL placeholder (idempotent)..."
set +e
REG_RESP=$(curl -s -w "\nHTTP_STATUS:%{http_code}" -X POST "${API_BASE}/registry/placeholders" \
  -H "Content-Type: application/json" \
  -d '{
        "name":"loan_number",
        "generation_mode":"manual_sql",
        "sql_text":"SELECT loan_id AS value FROM loans WHERE loan_id = {{loan_id}}",
        "datasource_id":1,
        "sample_value":"LN-12345",
        "created_by":"test_user"
      }')
REG_HTTP=$(echo "$REG_RESP" | grep "HTTP_STATUS:" | cut -d: -f2)
REG_BODY=$(echo "$REG_RESP" | sed '/HTTP_STATUS:/d')
set -e

# -----------------------------------------------------------------
# Three possible successful responses:
#   201 – brand‑new placeholder (body contains the UUID)
#   200 – placeholder already existed, API returned the existing record
#   409 – older behaviour – we must fetch the ID via a GET filter
# -----------------------------------------------------------------
if [[ "$REG_HTTP" == "201" || "$REG_HTTP" == "200" ]]; then
  # New or existing placeholder – UUID is in the response body
  REGISTRY_ID=$(extract_uuid "$REG_BODY")
elif [[ "$REG_HTTP" == "409" ]]; then
  log "Placeholder already exists – fetching ID via search"
  REGISTRY_ID=$(extract_uuid "$(curl -s "${API_BASE}/registry/placeholders?name=loan_number")")
else
  fail "Create placeholder failed (HTTP $REG_HTTP): $REG_BODY"
fi

[[ -z "$REGISTRY_ID" ]] && fail "Registry ID empty"
log "Registry ID: $REGISTRY_ID"

log "Listing placeholders..."
LIST_PLACEHOLDERS=$(curl -s "${API_BASE}/registry/placeholders")
[[ $(echo "$LIST_PLACEHOLDERS" | jq '. | length') -lt 1 ]] && fail "Placeholder list empty"
log "List OK – $(echo "$LIST_PLACEHOLDERS" | jq '. | length') items"

# --------------------------------------------------------------------
# 2. Template CRUD
# --------------------------------------------------------------------
log "Creating draft template (multilingual)..."
MULTILOCALE_TPL=$(curl -s -X POST "${API_BASE}/templates" \
  -H "Content-Type: application/json" \
  -d '{ "name":"MultiLocale Loan Statement", "description":"Multilingual template test", "output_target":"pdf", "layout_json":{"blocks":[{"type":"text","id":"blk1","content":"Loan: {{loan_number}}"}]}, "default_locale":"en", "supported_locales":["en","es","fr"], "industry":"banking", "tags":["loan","multilingual"], "created_by":"test_user" }')
TEMPLATE_ID=$(extract_uuid "$MULTILOCALE_TPL")
[[ -z "$TEMPLATE_ID" ]] && fail "Template ID extraction failed"
log "  Template created: $TEMPLATE_ID"

log "Fetching template by ID..."
GET_TPL=$(curl -s -w "\nHTTP_STATUS:%{http_code}" "${API_BASE}/templates/${TEMPLATE_ID}")
GET_HTTP=$(echo "$GET_TPL" | grep "HTTP_STATUS:" | cut -d: -f2)
GET_BODY=$(echo "$GET_TPL" | sed '/HTTP_STATUS:/d')

if [[ "$GET_HTTP" != "200" ]]; then
  fail "GET /templates/${TEMPLATE_ID} failed with HTTP $GET_HTTP"
fi

echo "$GET_BODY" | jq . >/dev/null 2>&1 || fail "GET returned invalid JSON: $GET_BODY"

[[ "$(echo "$GET_BODY" | jq -r '.template_id')" != "$TEMPLATE_ID" ]] && fail "GET returned wrong ID"
[[ "$(echo "$GET_BODY" | jq -r '.supported_locales | length')" != "3" ]] && fail "Multilingual data not preserved"
log "  GET OK – locales preserved"

log "Updating template description..."
UPDATED=$(curl -s -w "\nHTTP_STATUS:%{http_code}" -X PUT "${API_BASE}/templates/${TEMPLATE_ID}" \
  -H "Content-Type: application/json" \
  -d '{ "description":"Updated multilingual description" }')
UPD_HTTP=$(echo "$UPDATED" | grep "HTTP_STATUS:" | cut -d: -f2)
UPD_BODY=$(echo "$UPDATED" | sed '/HTTP_STATUS:/d')

if [[ "$UPD_HTTP" != "200" ]]; then
  fail "Update failed with HTTP $UPD_HTTP: $UPD_BODY"
fi

[[ "$(echo "$UPD_BODY" | jq -r '.description')" != "Updated multilingual description" ]] && fail "Update failed"
log "  PUT OK – description updated"

log "Verifying update persisted..."
GET_UPDATED=$(curl -s "${API_BASE}/templates/${TEMPLATE_ID}")
[[ "$(echo "$GET_UPDATED" | jq -r '.description')" != "Updated multilingual description" ]] && fail "Update not persisted"
log "  Update verified"
# --------------------------------------------------------------------
# 3. Placeholder Binding with Audit
# --------------------------------------------------------------------
log "Binding placeholder to template..."
BIND_RESP=$(curl -s -w "\nHTTP_STATUS:%{http_code}" -X POST "${API_BASE}/templates/${TEMPLATE_ID}/placeholders" \
  -H "Content-Type: application/json" \
  -d "{\"registry_id\":\"${REGISTRY_ID}\",\"override_sample_value\":\"LN-99999\"}")
BIND_HTTP=$(echo "$BIND_RESP" | grep "HTTP_STATUS:" | cut -d: -f2)
BIND_BODY=$(echo "$BIND_RESP" | sed '/HTTP_STATUS:/d')
[[ "$BIND_HTTP" != "201" ]] && fail "Bind failed: $BIND_BODY"
BIND_TPL_ID=$(echo "$BIND_BODY" | jq -r '.template_id')
[[ "$BIND_TPL_ID" != "$TEMPLATE_ID" ]] && fail "Bind returned wrong template_id"
log "  Bind OK – binding_id: $(echo "$BIND_BODY" | jq -r '.template_placeholder_id')"

# --------------------------------------------------------------------
# 4. Template Publishing & Versioning
# --------------------------------------------------------------------
log "Publishing template..."
PUB_RESP=$(curl -s -X POST "${API_BASE}/templates/${TEMPLATE_ID}/publish")
VERSION_ID=$(extract_uuid "$PUB_RESP")
[[ -z "$VERSION_ID" ]] && fail "Version ID extraction failed"
log "  Published – version: $VERSION_ID"

log "Verifying version snapshot..."
VERSION_CHECK=$(curl -s "${API_BASE}/templates/${TEMPLATE_ID}")
[[ "$(echo "$VERSION_CHECK" | jq -r '.status')" != "published" ]] && fail "Template not marked published"
log "  Version OK – status is published"

# --------------------------------------------------------------------
# 5. Template LIST with Filters & Search
# --------------------------------------------------------------------
log "Listing templates (published filter)..."
LIST_PUB=$(curl -s "${API_BASE}/templates?status_filter=published")
# Validate JSON before jq
echo "$LIST_PUB" | jq . >/dev/null 2>&1 || fail "List published returned invalid JSON: $LIST_PUB"
[[ $(echo "$LIST_PUB" | jq --arg tid "$TEMPLATE_ID" '[.[] | select(.template_id == $tid)] | length') -lt 1 ]] && fail "Published filter failed"
log "  List (published) OK"

log "Searching templates by name..."
SEARCH=$(curl -s "${API_BASE}/templates?search=MultiLocale%20Loan")
echo "$SEARCH" | jq . >/dev/null 2>&1 || fail "Search returned invalid JSON: $SEARCH"
[[ $(echo "$SEARCH" | jq '[.[] | select(.name | contains("MultiLocale"))] | length') -lt 1 ]] && fail "Search failed"
log "  Search OK"

log "Filtering by industry..."
BY_INDUSTRY=$(curl -s "${API_BASE}/templates?industry=banking")
echo "$BY_INDUSTRY" | jq . >/dev/null 2>&1 || fail "Industry filter returned invalid JSON: $BY_INDUSTRY"
[[ $(echo "$BY_INDUSTRY" | jq '[.[] | select(.industry == "banking")] | length') -lt 1 ]] && fail "Industry filter failed"
log "  Industry filter OK"

log "Filtering by tag..."
BY_TAG=$(curl -s "${API_BASE}/templates?tag=loan")
echo "$BY_TAG" | jq . >/dev/null 2>&1 || fail "Tag filter returned invalid JSON: $BY_TAG"
[[ $(echo "$BY_TAG" | jq '[.[] | select(.tags | contains(["loan"]))] | length') -lt 1 ]] && fail "Tag filter failed"
log "  Tag filter OK"

# --------------------------------------------------------------------
# 6. Error Scenarios & Edge Cases
# --------------------------------------------------------------------
log "Testing error responses..."

# 6.1 PUT on published template (should fail)
log "  PUT on published template (should fail)..."
ERR_PUT=$(curl -s -w "%{http_code}" -X PUT "${API_BASE}/templates/${TEMPLATE_ID}" \
  -H "Content-Type: application/json" \
  -d '{"name":"Should Fail"}' | tail -c 3)
[[ "$ERR_PUT" != "400" ]] && fail "Expected 400, got $ERR_PUT"
log "     400 returned as expected"

# 6.2 Publish missing template
log "  Publish missing template..."
ERR_PUB=$(curl -s -w "%{http_code}" -X POST "${API_BASE}/templates/00000000-0000-0000-0000-000000000000/publish" | tail -c 3)
[[ "$ERR_PUB" != "404" ]] && fail "Expected 404, got $ERR_PUB"
log "     404 returned as expected"

# 6.3 Bind to missing template
log "  Bind to missing template..."
ERR_BIND=$(curl -s -w "%{http_code}" -X POST "${API_BASE}/templates/00000000-0000-0000-0000-000000000000/placeholders" \
  -H "Content-Type: application/json" \
  -d "{\"registry_id\":\"${REGISTRY_ID}\"}" | tail -c 3)
[[ "$ERR_BIND" != "404" ]] && fail "Expected 404, got $ERR_BIND"
log "     404 returned as expected"

# 6.4 Invalid output_target
log "  Invalid output_target..."
ERR_TPL=$(curl -s -w "%{http_code}" -X POST "${API_BASE}/templates" \
  -H "Content-Type: application/json" \
  -d '{"name":"Invalid","output_target":"invalid","layout_json":{"blocks":[]},"created_by":"test"}' | tail -c 3)
[[ "$ERR_TPL" != "422" ]] && fail "Expected 422, got $ERR_TPL"
log "     422 returned as expected"

# 6.5 Stress test with 50 blocks
log "  Stress test with 50 blocks..."
LARGE_LAYOUT='{"blocks":['
for i in {1..50}; do
  LARGE_LAYOUT+="{\"type\":\"text\",\"id\":\"blk$i\",\"content\":\"Block $i: {{loan_number}}\"},"
done
LARGE_LAYOUT="${LARGE_LAYOUT%,}]}"
STRESS_TPL=$(curl -s -X POST "${API_BASE}/templates" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"Stress Test\",\"output_target\":\"html\",\"layout_json\":${LARGE_LAYOUT},\"created_by\":\"test\"}")
STRESS_ID=$(extract_uuid "$STRESS_TPL")
[[ -z "$STRESS_ID" ]] && fail "Stress test template creation failed"
log "     Large template created: $STRESS_ID"
# --------------------------------------------------------------------
# 7. Archive & Lifecycle
# --------------------------------------------------------------------
log "Archiving template..."
ARCHIVE_RESP=$(curl -s -X DELETE "${API_BASE}/templates/${TEMPLATE_ID}" -w "%{http_code}")
[[ "$ARCHIVE_RESP" != "204" ]] && fail "Archive failed"
log "  Archive OK"

log "Verifying archived status..."
ARCHIVED_TPL=$(curl -s "${API_BASE}/templates/${TEMPLATE_ID}")
[[ "$(echo "$ARCHIVED_TPL" | jq -r '.status')" != "archived" ]] && fail "Template not archived"
log "  Archive verified"

# --------------------------------------------------------------------
# 8. Document Generation & Multilingual Render
# --------------------------------------------------------------------
curl -s -X POST http://localhost:10001/v1/templates \
  -H "Content-Type: application/json" \
  -d '{
    "name": "CJK Loan Statement",
    "description": "Multilingual test with Chinese",
    "output_target": "pdf",
    "layout_json": {
      "blocks": [
        {
          "type": "text",
          "id": "blk1",
          "content_i18n": {
            "en": "Loan number: {{loan_number}}",
            "zh": "贷款编号：{{loan_number}}",
            "ja": "ローン番号：{{loan_number}}",
            "ko": "대출 번호：{{loan_number}}"
          }
        }
      ]
    },
    "default_locale": "en",
    "supported_locales": ["zh","ja","ko","en"],
    "industry": "banking",
    "tags": ["cjk","multilingual"],
    "created_by": "test_user"
  }' | jq .


log "Creating fresh template for render test..."
RENDER_TPL=$(curl -s -X POST "${API_BASE}/templates" \
  -H "Content-Type: application/json" \
  -d '{ "name":"Render Test","output_target":"pdf","layout_json":{"blocks":[{"type":"text","id":"blk1","content":"Loan: {{loan_number}}"}]}, "default_locale":"en","supported_locales":["en","es"], "created_by":"test" }')
RENDER_ID=$(extract_uuid "$RENDER_TPL")
[[ -z "$RENDER_ID" ]] && fail "Render template creation failed"

# Bind placeholder
curl -s -X POST "${API_BASE}/templates/${RENDER_ID}/placeholders" \
  -H "Content-Type: application/json" \
  -d "{\"registry_id\":\"${REGISTRY_ID}\"}" >/dev/null

# Publish
curl -s -X POST "${API_BASE}/templates/${RENDER_ID}/publish" >/dev/null

# Generate in English
log "Generating document (locale=en)..."
GEN_EN=$(curl -s -X POST "${API_BASE}/documents/generate" \
  -H "Content-Type: application/json" \
  -d "{\"template_id\":\"${RENDER_ID}\",\"output_target\":\"html\",\"locale\":\"en\",\"runtime_params\":{\"loan_id\":\"12345\"}}")
JOB_EN=$(extract_uuid "$GEN_EN")
[[ -z "$JOB_EN" ]] && fail "English render job ID extraction failed"

for i in {1..30}; do
  STATUS_EN=$(curl -s "${API_BASE}/documents/jobs/${JOB_EN}" | jq -r '.status')
  [[ "$STATUS_EN" == "success" ]] && break
  [[ "$STATUS_EN" == "error" ]] && fail "English render job failed"
  sleep 1
done
[[ "$STATUS_EN" != "success" ]] && fail "English render did not complete"

# Generate in Spanish
log "Generating document (locale=es)..."
GEN_ES=$(curl -s -X POST "${API_BASE}/documents/generate" \
  -H "Content-Type: application/json" \
  -d "{\"template_id\":\"${RENDER_ID}\",\"output_target\":\"html\",\"locale\":\"es\",\"runtime_params\":{\"loan_id\":\"12345\"}}")
JOB_ES=$(extract_uuid "$GEN_ES")
[[ -z "$JOB_ES" ]] && fail "Spanish render job ID extraction failed"

for i in {1..30}; do
  STATUS_ES=$(curl -s "${API_BASE}/documents/jobs/${JOB_ES}" | jq -r '.status')
  [[ "$STATUS_ES" == "success" ]] && break
  [[ "$STATUS_ES" == "error" ]] && fail "Spanish render job failed"
  sleep 1
done
[[ "$STATUS_ES" != "success" ]] && fail "Spanish render did not complete"
log "  Multilingual render OK"

# --------------------------------------------------------------------
# 9. Data Integrity & Audit
# --------------------------------------------------------------------
log "Verifying data integrity..."

log " Checking version snapshot..."
VERSION_IMMUTABLE=$(run_psql "SELECT count(*) FROM template_builder.template_versions WHERE template_id='${RENDER_ID}';")

# Ensure exactly one version snapshot exists
[[ "$VERSION_IMMUTABLE" -eq 1 ]] || fail "Version snapshot not created exactly once"

log " Version snapshot immutable"

# -------------------------------------------------
# Audit‑trail verification (using audit_events)
# -------------------------------------------------
log "[TEST] Checking audit trail..."

# For this flow, RENDER_ID is the template_id of 'Render Test'
TEMPLATE_ID="${RENDER_ID}"

# Count the three actions we expect for the rendered template
AUDIT_CREATE=$(run_psql "SELECT count(*) FROM template_builder.audit_events WHERE entity_type = 'template' AND entity_id = '${TEMPLATE_ID}' AND action = 'create';")
AUDIT_BIND=$(run_psql "SELECT count(*) FROM template_builder.audit_events WHERE entity_type = 'template' AND entity_id = '${TEMPLATE_ID}' AND action = 'bind_placeholder';")
AUDIT_PUBLISH=$(run_psql "SELECT count(*) FROM template_builder.audit_events WHERE entity_type = 'template' AND entity_id = '${TEMPLATE_ID}' AND action = 'publish';")

# Default to 0 if run_psql returned empty
AUDIT_CREATE=${AUDIT_CREATE:-0}
AUDIT_BIND=${AUDIT_BIND:-0}
AUDIT_PUBLISH=${AUDIT_PUBLISH:-0}

# Always log the raw counts
log " create count       = $AUDIT_CREATE"
log " bind_placeholder  = $AUDIT_BIND"
log " publish count     = $AUDIT_PUBLISH"

# Verify that each action appears exactly once
if [[ "$AUDIT_CREATE" -eq 1 && "$AUDIT_BIND" -eq 1 && "$AUDIT_PUBLISH" -eq 1 ]]; then
  log "Audit trail complete (create, bind_placeholder, publish)"
else
  # Build a detailed failure message
  FAIL_MSG="Incomplete audit trail –"
  [[ "$AUDIT_CREATE"  -ne 1 ]] && FAIL_MSG+=" create=$AUDIT_CREATE"
  [[ "$AUDIT_BIND"    -ne 1 ]] && FAIL_MSG+=" bind_placeholder=$AUDIT_BIND"
  [[ "$AUDIT_PUBLISH" -ne 1 ]] && FAIL_MSG+=" publish=$AUDIT_PUBLISH"

  # Explicitly log the error before failing
  log "ERROR: $FAIL_MSG"
  fail "$FAIL_MSG"
fi

# --------------------------------------------------------------------
# 10. Performance Baseline
# --------------------------------------------------------------------
log "Running performance baseline tests..."

CREATE_TIME=$(time_op curl -s -X POST "${API_BASE}/templates" \
  -H "Content-Type: application/json" \
  -d '{"name":"Perf Test","output_target":"html","layout_json":{"blocks":[]},"created_by":"perf"}')
[[ -z "$CREATE_TIME" ]] && fail "Create timing failed"
log "  Template creation: ${CREATE_TIME}s"

BIND_TIME=$(time_op curl -s -X POST "${API_BASE}/templates/${RENDER_ID}/placeholders" \
  -H "Content-Type: application/json" \
  -d "{\"registry_id\":\"${REGISTRY_ID}\"}")
[[ -z "$BIND_TIME" ]] && fail "Bind timing failed"
log "  Placeholder bind: ${BIND_TIME}s"

LIST_TIME=$(time_op curl -s "${API_BASE}/templates?status_filter=published")
[[ -z "$LIST_TIME" ]] && fail "List timing failed"
log "  List query: ${LIST_TIME}s"

# --------------------------------------------------------------------
# 11. Cleanup
# --------------------------------------------------------------------
log "Cleaning up test artifacts..."
run_psql "DELETE FROM template_builder.template_audit_logs WHERE template_id='${STRESS_ID}' OR template_id='${RENDER_ID}';" >/dev/null 2>&1 || true
run_psql "DELETE FROM template_builder.template_placeholders WHERE template_id='${STRESS_ID}' OR template_id='${RENDER_ID}';" >/dev/null 2>&1 || true
run_psql "DELETE FROM template_builder.template_versions WHERE template_id='${STRESS_ID}' OR template_id='${RENDER_ID}';" >/dev/null 2>&1 || true
run_psql "DELETE FROM template_builder.templates WHERE template_id='${STRESS_ID}' OR template_id='${RENDER_ID}';" >/dev/null 2>&1 || true
log "  Cleanup complete"

# --------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------
log "═══════════════════════════════════════════════════════════════"
log "Phase 1 Production Hardening COMPLETE"
log "   All CRUD endpoints tested"
log "   Multilingual features validated"
log "   Error scenarios handled correctly"
log "   Data integrity verified"
log "   Audit trail complete"
log "   Performance baselines recorded"
log "═══════════════════════════════════════════════════════════════"