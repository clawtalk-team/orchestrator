#!/bin/bash
# Setup and test script for orchestrator with auth-gateway integration

set -e

echo "======================================"
echo "Orchestrator Setup and Test Script"
echo "======================================"
echo ""

# Configuration from docker-compose.yml and .env
AUTH_GATEWAY_URL="${AUTH_GATEWAY_URL:-https://your-auth-gateway.execute-api.your-region.amazonaws.com}"
AUTH_GATEWAY_API_KEY="${AUTH_GATEWAY_API_KEY?'AUTH_GATEWAY_API_KEY not set'}"
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY?'ANTHROPIC_API_KEY not set'}"
OPENCLAW_GATEWAY_TOKEN="${OPENCLAW_GATEWAY_TOKEN:-test-token-123}"
VOICE_GATEWAY_URL="http://your-voice-gateway.your-region.elb.amazonaws.com"
DYNAMODB_TABLE="openclaw-containers"
DYNAMODB_REGION="ap-southeast-2"

echo "Using configuration:"
echo "  Auth Gateway: $AUTH_GATEWAY_URL"
echo "  DynamoDB Table: $DYNAMODB_TABLE"
echo "  DynamoDB Region: $DYNAMODB_REGION"
echo ""

# Step 1: Verify auth-gateway and get user_id
echo "[1/5] Verifying API key with auth-gateway..."
USER_RESPONSE=$(curl -s -X GET "$AUTH_GATEWAY_URL/auth" \
    -H "Authorization: Bearer $AUTH_GATEWAY_API_KEY")

USER_ID=$(echo "$USER_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('user_id', ''))" 2>/dev/null || echo "")

if [ -z "$USER_ID" ]; then
    echo "✗ Failed to get user_id from auth-gateway"
    echo "Response: $USER_RESPONSE"
    exit 1
fi

echo "✓ Got user_id: $USER_ID"
echo ""

# Step 2: Setup system defaults in DynamoDB
echo "[2/5] Setting up system defaults in DynamoDB..."

SYSTEM_CONFIG=$(cat <<EOF
{
  "pk": {"S": "SYSTEM"},
  "sk": {"S": "CONFIG#defaults"},
  "config_type": {"S": "system_config"},
  "auth_gateway_url": {"S": "$AUTH_GATEWAY_URL"},
  "openclaw_url": {"S": "http://localhost:18789"},
  "openclaw_token": {"S": "$OPENCLAW_GATEWAY_TOKEN"},
  "voice_gateway_url": {"S": "$VOICE_GATEWAY_URL"},
  "updated_at": {"S": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"}
}
EOF
)

aws dynamodb put-item \
    --table-name "$DYNAMODB_TABLE" \
    --item "$SYSTEM_CONFIG" \
    --region "$DYNAMODB_REGION" > /dev/null

echo "✓ System defaults configured"
echo ""

# Step 3: Setup user config in DynamoDB
echo "[3/5] Setting up user config in DynamoDB..."

USER_CONFIG=$(cat <<EOF
{
  "pk": {"S": "USER#$USER_ID"},
  "sk": {"S": "CONFIG#default"},
  "config_type": {"S": "user_config"},
  "user_id": {"S": "$USER_ID"},
  "llm_provider": {"S": "anthropic"},
  "openclaw_model": {"S": "claude-3-haiku-20240307"},
  "auth_gateway_api_key": {"S": "$AUTH_GATEWAY_API_KEY"},
  "anthropic_api_key": {"S": "$ANTHROPIC_API_KEY"},
  "created_at": {"S": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"},
  "updated_at": {"S": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"}
}
EOF
)

aws dynamodb put-item \
    --table-name "$DYNAMODB_TABLE" \
    --item "$USER_CONFIG" \
    --region "$DYNAMODB_REGION" > /dev/null

echo "✓ User config configured for user_id: $USER_ID"
echo ""

# Step 4: Verify orchestrator is running
echo "[4/5] Checking orchestrator status..."

if curl -s -f http://localhost:8000/health > /dev/null 2>&1; then
    echo "✓ Orchestrator is running"
else
    echo "✗ Orchestrator is not running"
    echo ""
    echo "Please start the orchestrator:"
    echo "  # Navigate to the orchestrator directory"
    echo "  uvicorn app.main:app --reload --port 8000"
    echo ""
    echo "Then run this script again."
    exit 1
fi
echo ""

# Step 5: Test container creation
echo "[5/5] Testing container creation..."

CONTAINER_RESPONSE=$(curl -s -X POST http://localhost:8000/containers \
    -H "Authorization: Bearer $AUTH_GATEWAY_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"config_name": "default"}')

echo "Response: $CONTAINER_RESPONSE"
echo ""

CONTAINER_ID=$(echo "$CONTAINER_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('container_id', ''))" 2>/dev/null || echo "")

if [ -n "$CONTAINER_ID" ]; then
    echo "✓ Container created successfully!"
    echo "  Container ID: $CONTAINER_ID"
    echo ""
    echo "Next steps:"
    echo "1. Check container status:"
    echo "   curl http://localhost:8000/containers/$CONTAINER_ID \\"
    echo "     -H 'Authorization: Bearer $AUTH_GATEWAY_API_KEY'"
    echo ""
    echo "2. List all containers:"
    echo "   curl http://localhost:8000/containers \\"
    echo "     -H 'Authorization: Bearer $AUTH_GATEWAY_API_KEY'"
    echo ""
    echo "3. If using ECS, check task in AWS console:"
    echo "   https://console.aws.amazon.com/ecs/v2/clusters/your-cluster/tasks"
    echo ""
else
    echo "✗ Container creation failed"
    echo "Response: $CONTAINER_RESPONSE"
    exit 1
fi

echo "======================================"
echo "Setup Complete!"
echo "======================================"
echo ""
echo "Configuration Summary:"
echo "  User ID: $USER_ID"
echo "  API Key: ${AUTH_GATEWAY_API_KEY:0:20}..."
echo "  DynamoDB Table: $DYNAMODB_TABLE"
echo "  System defaults: ✓"
echo "  User config: ✓"
echo "  Container: ✓"
echo ""
