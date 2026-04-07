#!/bin/bash
# Get logs for a specific container

set -e

CONTAINER_ID="${1}"
USER_ID="${2:-andrew}"
PROFILE="${AWS_PROFILE:-personal}"
REGION="ap-southeast-2"
TABLE_NAME="openclaw-containers-dev"
LOG_GROUP="/ecs/openclaw-agent-dev"

if [ -z "$CONTAINER_ID" ]; then
    echo "Usage: $0 <container-id> [user-id]"
    echo ""
    echo "Example: $0 oc-18c03ca7 andrew"
    echo ""
    echo "List your containers first:"
    echo "  curl https://prz6mum7c7.execute-api.ap-southeast-2.amazonaws.com/containers \\"
    echo "    -H 'Authorization: Bearer ${USER_ID}:your-token-here'"
    exit 1
fi

echo "🔍 Fetching logs for container: $CONTAINER_ID (user: $USER_ID)"
echo ""

# Get task ARN from DynamoDB
echo "📦 Looking up task ARN in DynamoDB..."
TASK_ARN=$(aws --profile "$PROFILE" dynamodb get-item \
  --table-name "$TABLE_NAME" \
  --region "$REGION" \
  --key "{\"pk\":{\"S\":\"USER#${USER_ID}\"},\"sk\":{\"S\":\"CONTAINER#${CONTAINER_ID}\"}}" \
  --query 'Item.task_arn.S' \
  --output text 2>/dev/null)

if [ -z "$TASK_ARN" ] || [ "$TASK_ARN" = "None" ]; then
    echo "❌ Container not found: $CONTAINER_ID"
    echo ""
    echo "Make sure:"
    echo "  1. Container ID is correct"
    echo "  2. User ID is correct (currently: $USER_ID)"
    echo "  3. Container exists in DynamoDB"
    exit 1
fi

# Extract task ID from ARN
TASK_ID=$(echo "$TASK_ARN" | rev | cut -d'/' -f1 | rev)
echo "✅ Found task: $TASK_ID"
echo ""

# Check task status
echo "🔄 Checking task status..."
TASK_STATUS=$(aws --profile "$PROFILE" ecs describe-tasks \
  --cluster clawtalk-dev \
  --region "$REGION" \
  --tasks "$TASK_ARN" \
  --query 'tasks[0].lastStatus' \
  --output text 2>/dev/null || echo "UNKNOWN")

echo "   Status: $TASK_STATUS"
echo ""

# View logs
echo "📋 Container logs (last 30 minutes):"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
aws --profile "$PROFILE" logs tail "$LOG_GROUP" \
  --region "$REGION" \
  --since 30m \
  --format short \
  --filter-pattern "$TASK_ID" 2>/dev/null || {
    echo "⚠️  No logs found yet. Container may still be starting."
    echo ""
    echo "💡 Tip: Try following logs in real-time:"
    echo "   aws --profile $PROFILE logs tail $LOG_GROUP --region $REGION --follow"
}
