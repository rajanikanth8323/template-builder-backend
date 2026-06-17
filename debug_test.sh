#!/usr/bin/env bash
set -e

API_BASE="http://localhost:10001/v1"

echo "=== 1. Checking if /healthz is reachable ==="
curl -v http://localhost:10001/healthz 2>&1 | head -20
echo ""

echo "=== 2. Checking if /v1/registry/placeholders endpoint exists ==="
curl -X POST "$API_BASE/registry/placeholders" \
  -H "Content-Type: application/json" \
  -d '{}' \
  -w "\nHTTP Status: %{http_code}\n" \
  -s
echo ""

echo "=== 3. Testing placeholder creation with full trace ==="
REGISTRY_RESPONSE=$(curl -X POST "$API_BASE/registry/placeholders/" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "loan_number",
    "category": "loan",
    "prompt": "SELECT loan_id AS value FROM loans WHERE loan_id = {{loan_id}}",
    "format_json": {"type": "string"},
    "datasource_id": 1,
    "sample_value": "LN-12345"
  }' \
  -w "\nHTTP Status: %{http_code}" \
  -s)

echo "Raw response: $REGISTRY_RESPONSE"

HTTP_CODE=$(echo "$REGISTRY_RESPONSE" | tail -1 | grep -o '[0-9]\{3\}')
echo "HTTP Status Code: $HTTP_CODE"

if [ "$HTTP_CODE" != "201" ]; then
  echo "ERROR: Expected 201 Created, got $HTTP_CODE"
fi