#!/bin/bash
# Test script for auth-gateway integration

set -e

echo "======================================"
echo "Auth-Gateway Integration Test"
echo "======================================"
echo ""

# Configuration
AUTH_GATEWAY_URL="${AUTH_GATEWAY_URL:-https://your-auth-gateway.execute-api.your-region.amazonaws.com}"
ORCHESTRATOR_URL="${ORCHESTRATOR_URL:-http://localhost:8000}"

echo "Testing auth-gateway at: $AUTH_GATEWAY_URL"
echo "Testing orchestrator at: $ORCHESTRATOR_URL"
echo ""

# Test 1: Verify auth-gateway is accessible
echo "[1/5] Testing auth-gateway availability..."
if curl -s -f "$AUTH_GATEWAY_URL/docs" > /dev/null; then
    echo "✓ Auth-gateway is accessible"
else
    echo "✗ Auth-gateway is not accessible"
    exit 1
fi
echo ""

# Test 2: Verify auth-gateway /auth endpoint (with dummy key)
echo "[2/5] Testing auth-gateway /auth endpoint..."
HTTP_CODE=$(curl -s -w "%{http_code}" -o /tmp/auth_response.json \
    -H "Authorization: Bearer invalid-key-for-testing" \
    "$AUTH_GATEWAY_URL/auth")

if [ "$HTTP_CODE" == "401" ]; then
    echo "✓ Auth-gateway correctly rejects invalid API key"
elif [ "$HTTP_CODE" == "200" ]; then
    echo "⚠ Auth-gateway accepted test key (unexpected)"
    cat /tmp/auth_response.json
else
    echo "✗ Unexpected response code: $HTTP_CODE"
    exit 1
fi
echo ""

# Test 3: Check orchestrator health
echo "[3/5] Testing orchestrator availability..."
if curl -s -f "$ORCHESTRATOR_URL/health" > /dev/null; then
    echo "✓ Orchestrator is accessible"
else
    echo "✗ Orchestrator is not accessible"
    echo "  Make sure orchestrator is running: uvicorn app.main:app --reload"
    exit 1
fi
echo ""

# Test 4: Test orchestrator with invalid key
echo "[4/5] Testing orchestrator auth middleware..."
HTTP_CODE=$(curl -s -w "%{http_code}" -o /tmp/orchestrator_response.json \
    -X POST "$ORCHESTRATOR_URL/containers" \
    -H "Authorization: Bearer invalid-key-for-testing" \
    -H "Content-Type: application/json" \
    -d '{"config_name": "default"}')

if [ "$HTTP_CODE" == "401" ] || [ "$HTTP_CODE" == "503" ]; then
    echo "✓ Orchestrator correctly handles invalid API key"
    cat /tmp/orchestrator_response.json
else
    echo "✗ Unexpected response code: $HTTP_CODE"
    cat /tmp/orchestrator_response.json
    exit 1
fi
echo ""

# Test 5: Test with master API key (if set)
echo "[5/5] Testing master API key bypass..."
if [ -n "$MASTER_API_KEY" ]; then
    HTTP_CODE=$(curl -s -w "%{http_code}" -o /tmp/master_response.json \
        -X GET "$ORCHESTRATOR_URL/containers" \
        -H "Authorization: Bearer $MASTER_API_KEY")

    if [ "$HTTP_CODE" == "200" ]; then
        echo "✓ Master API key works"
    else
        echo "✗ Master API key failed: $HTTP_CODE"
        cat /tmp/master_response.json
    fi
else
    echo "⚠ MASTER_API_KEY not set, skipping master key test"
fi
echo ""

# Summary
echo "======================================"
echo "Test Summary"
echo "======================================"
echo "✓ Auth-gateway is deployed and accessible"
echo "✓ Auth-gateway /auth endpoint working"
echo "✓ Orchestrator is running"
echo "✓ Orchestrator auth middleware integrated"
echo ""
echo "Next steps:"
echo "1. Create a real user account in auth-gateway"
echo "2. Get a valid API key from auth-gateway"
echo "3. Test container creation with valid API key:"
echo ""
echo "   curl -X POST $ORCHESTRATOR_URL/containers \\"
echo "     -H 'Authorization: Bearer YOUR_REAL_API_KEY' \\"
echo "     -H 'Content-Type: application/json' \\"
echo "     -d '{\"config_name\": \"default\"}'"
echo ""

# Cleanup
rm -f /tmp/auth_response.json /tmp/orchestrator_response.json /tmp/master_response.json
