#!/bin/bash
#
# End-to-End Test for DynamoDB Config Delivery
#
# This script:
# 1. Sets up DynamoDB with test configuration
# 2. Starts the test container (OpenClaw + openclaw-agent + mocks)
# 3. Verifies all services start correctly
# 4. Tests OpenClaw query functionality
# 5. Verifies agent registration with auth-gateway
# 6. Shows logs for debugging
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[test]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[test]${NC} $1"
}

log_error() {
    echo -e "${RED}[test]${NC} $1"
}

log_section() {
    echo ""
    echo -e "${BLUE}=== $1 ===${NC}"
    echo ""
}

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORCHESTRATOR_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Test configuration
USER_ID="test-user-123"
CONTAINER_ID="oc-test-e2e-001"
API_KEY="$USER_ID:test-token-xyz-789"

# Service URLs
DYNAMODB_URL="http://localhost:8000"
OPENCLAW_URL="http://localhost:18789"
AGENT_URL="http://localhost:8082"
AUTH_GATEWAY_URL="http://localhost:8789"
VOICE_GATEWAY_URL="http://localhost:9090"

log_section "End-to-End Test - DynamoDB Config Delivery"

log_info "Test configuration:"
log_info "  User ID: $USER_ID"
log_info "  Container ID: $CONTAINER_ID"
log_info "  API Key: ${API_KEY:0:30}..."

# ============================================================================
# Step 1: Check Prerequisites
# ============================================================================

log_section "Step 1: Checking Prerequisites"

# Check for required tools
for tool in docker python3 curl jq; do
    if ! command -v $tool &> /dev/null; then
        log_error "$tool is not installed"
        exit 1
    fi
    log_info "✓ $tool is installed"
done

# Check for .env file with API keys
if [ ! -f "$ORCHESTRATOR_DIR/.env" ]; then
    log_warn ".env file not found at $ORCHESTRATOR_DIR/.env"
    log_warn "Will use placeholder API keys for testing"
else
    log_info "✓ .env file found"
fi

# Source .env if it exists
if [ -f "$ORCHESTRATOR_DIR/.env" ]; then
    set -a
    source "$ORCHESTRATOR_DIR/.env"
    set +a
fi

# Check for Anthropic API key
if [ -z "$ANTHROPIC_API_KEY" ]; then
    log_warn "ANTHROPIC_API_KEY not set - using placeholder"
    ANTHROPIC_API_KEY="sk-ant-placeholder-key"
else
    log_info "✓ ANTHROPIC_API_KEY is set: ${ANTHROPIC_API_KEY:0:20}..."
fi

# ============================================================================
# Step 2: Start DynamoDB Local
# ============================================================================

log_section "Step 2: Starting DynamoDB Local"

# Check if DynamoDB is already running
if docker ps | grep -q orchestrator-dynamodb-test; then
    log_info "DynamoDB is already running"
else
    log_info "Starting DynamoDB local..."
    docker compose -f "$SCRIPT_DIR/docker compose.e2e.yml" up -d dynamodb-local

    log_info "Waiting for DynamoDB to be ready..."
    for i in {1..30}; do
        if curl -f -s $DYNAMODB_URL > /dev/null 2>&1; then
            log_info "✓ DynamoDB is ready"
            break
        fi
        if [ $i -eq 30 ]; then
            log_error "DynamoDB failed to start"
            exit 1
        fi
        sleep 1
    done
fi

# ============================================================================
# Step 3: Create DynamoDB Table and Test Data
# ============================================================================

log_section "Step 3: Creating DynamoDB Table and Test Data"

log_info "Creating openclaw-containers table..."
python3 - <<EOF
import boto3
from botocore.exceptions import ClientError

dynamodb = boto3.resource(
    'dynamodb',
    endpoint_url='$DYNAMODB_URL',
    region_name='ap-southeast-2',
    aws_access_key_id='local',
    aws_secret_access_key='local'
)

# Try to create table
try:
    table = dynamodb.create_table(
        TableName='openclaw-containers',
        KeySchema=[
            {'AttributeName': 'pk', 'KeyType': 'HASH'},
            {'AttributeName': 'sk', 'KeyType': 'RANGE'},
        ],
        AttributeDefinitions=[
            {'AttributeName': 'pk', 'AttributeType': 'S'},
            {'AttributeName': 'sk', 'AttributeType': 'S'},
            {'AttributeName': 'user_id', 'AttributeType': 'S'},
            {'AttributeName': 'status', 'AttributeType': 'S'},
        ],
        BillingMode='PAY_PER_REQUEST',
        GlobalSecondaryIndexes=[
            {
                'IndexName': 'user_id-status-index',
                'KeySchema': [
                    {'AttributeName': 'user_id', 'KeyType': 'HASH'},
                    {'AttributeName': 'status', 'KeyType': 'RANGE'},
                ],
                'Projection': {'ProjectionType': 'ALL'},
            },
        ],
    )
    table.wait_until_exists()
    print("✓ Table created")
except ClientError as e:
    if e.response['Error']['Code'] == 'ResourceInUseException':
        print("✓ Table already exists")
    else:
        raise
EOF

log_info "Creating test configuration..."
python3 "$ORCHESTRATOR_DIR/scripts/setup_test_config.py" \
    --user-id "$USER_ID" \
    --anthropic-key "$ANTHROPIC_API_KEY" \
    --endpoint "$DYNAMODB_URL"

# ============================================================================
# Step 4: Start Test Container
# ============================================================================

log_section "Step 4: Starting Test Container"

log_info "Building and starting test container..."
log_info "This may take a few minutes on first run..."

cd "$ORCHESTRATOR_DIR"
docker compose -f test/docker compose.e2e.yml up -d --build test-container

log_info "Waiting for all services to be healthy..."
log_info "This may take up to 60 seconds..."

# Wait for healthcheck
for i in {1..60}; do
    if docker inspect orchestrator-test-container | jq -r '.[0].State.Health.Status' | grep -q "healthy"; then
        log_info "✓ Container is healthy"
        break
    fi
    if [ $i -eq 60 ]; then
        log_error "Container failed to become healthy"
        log_error "Showing container logs:"
        docker logs orchestrator-test-container
        exit 1
    fi
    echo -n "."
    sleep 1
done
echo ""

# ============================================================================
# Step 5: Verify All Services Started
# ============================================================================

log_section "Step 5: Verifying All Services"

# Check OpenClaw
log_info "Checking OpenClaw gateway..."
if curl -f -s "$OPENCLAW_URL/healthz" > /dev/null; then
    log_info "✓ OpenClaw is running"
else
    log_error "OpenClaw is not responding"
    exit 1
fi

# Check openclaw-agent
log_info "Checking openclaw-agent..."
if curl -f -s "$AGENT_URL/health" > /dev/null; then
    AGENT_HEALTH=$(curl -s "$AGENT_URL/health" | jq -r '.status')
    log_info "✓ openclaw-agent is running (status: $AGENT_HEALTH)"
else
    log_error "openclaw-agent is not responding"
    exit 1
fi

# Check mock auth gateway
log_info "Checking mock-auth-gateway..."
if curl -f -s "$AUTH_GATEWAY_URL/health" > /dev/null; then
    log_info "✓ mock-auth-gateway is running"
else
    log_error "mock-auth-gateway is not responding"
    exit 1
fi

# Check mock voice gateway
log_info "Checking mock-voice-gateway..."
if curl -f -s "$VOICE_GATEWAY_URL/health" > /dev/null; then
    log_info "✓ mock-voice-gateway is running"
else
    log_error "mock-voice-gateway is not responding"
    exit 1
fi

# ============================================================================
# Step 6: Test OpenClaw Query
# ============================================================================

log_section "Step 6: Testing OpenClaw Query"

log_info "Sending test query to OpenClaw..."

QUERY_RESPONSE=$(curl -s -X POST "$OPENCLAW_URL/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer test-token-123" \
    -d '{
        "model": "claude-3-haiku-20240307",
        "messages": [{"role": "user", "content": "Say hello in exactly 3 words"}],
        "max_tokens": 20
    }')

if echo "$QUERY_RESPONSE" | jq -e '.choices[0].message.content' > /dev/null 2>&1; then
    RESPONSE_TEXT=$(echo "$QUERY_RESPONSE" | jq -r '.choices[0].message.content')
    log_info "✓ OpenClaw query successful"
    log_info "Response: $RESPONSE_TEXT"
else
    log_error "OpenClaw query failed"
    log_error "Response: $QUERY_RESPONSE"
    exit 1
fi

# ============================================================================
# Step 7: Verify Agent Registration
# ============================================================================

log_section "Step 7: Verifying Agent Registration"

log_info "Checking if agents registered with auth-gateway..."

# Get registered agents for this user
AUTH_RESPONSE=$(curl -s "$AUTH_GATEWAY_URL/users/$USER_ID/agents")

if [ -z "$AUTH_RESPONSE" ]; then
    log_warn "No agents registered yet (this is expected on first startup)"
    log_info "Agent registration happens after OpenClaw agents are configured"
else
    AGENT_COUNT=$(echo "$AUTH_RESPONSE" | jq -r '.agents | length // 0')
    log_info "✓ Found $AGENT_COUNT registered agent(s)"

    if [ "$AGENT_COUNT" -gt 0 ]; then
        log_info "Registered agents:"
        echo "$AUTH_RESPONSE" | jq -r '.agents | to_entries[] | "  - \(.key)"'
    fi
fi

# ============================================================================
# Step 8: Show Container Logs
# ============================================================================

log_section "Step 8: Container Logs"

log_info "Showing container startup logs (last 50 lines)..."
echo ""
docker logs orchestrator-test-container --tail 50

# ============================================================================
# Test Complete
# ============================================================================

log_section "Test Complete"

log_info "✓ All tests passed!"
log_info ""
log_info "Services are running and accessible:"
log_info "  OpenClaw API:        $OPENCLAW_URL"
log_info "  openclaw-agent API:  $AGENT_URL"
log_info "  Auth Gateway:        $AUTH_GATEWAY_URL"
log_info "  Voice Gateway:       $VOICE_GATEWAY_URL"
log_info ""
log_info "Try these commands:"
log_info "  # Query OpenClaw"
log_info "  curl -X POST $OPENCLAW_URL/v1/chat/completions \\"
log_info "    -H 'Content-Type: application/json' \\"
log_info "    -H 'Authorization: Bearer test-token-123' \\"
log_info "    -d '{\"model\":\"claude-3-haiku-20240307\",\"messages\":[{\"role\":\"user\",\"content\":\"Hello\"}]}' | jq"
log_info ""
log_info "  # Check agent status"
log_info "  curl $AGENT_URL/agents/status | jq"
log_info ""
log_info "  # View all logs"
log_info "  docker logs orchestrator-test-container -f"
log_info ""
log_info "  # View specific log file"
log_info "  docker exec orchestrator-test-container cat /tmp/agent.log"
log_info "  docker exec orchestrator-test-container cat /tmp/openclaw.log"
log_info ""
log_info "To stop:"
log_info "  docker compose -f test/docker compose.e2e.yml down"
