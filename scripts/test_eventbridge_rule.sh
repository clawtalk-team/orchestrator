#!/bin/bash
#
# Test EventBridge rule by checking if it processes events correctly.
#
# Usage:
#   AWS_PROFILE=personal ./scripts/test_eventbridge_rule.sh
#

set -e

AWS_PROFILE="${AWS_PROFILE:-personal}"
AWS_REGION="${AWS_REGION:-ap-southeast-2}"
RULE_NAME="orchestrator-ecs-task-state-change"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

echo "═══════════════════════════════════════════════════════════════"
echo "EventBridge Rule Test"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# 1. Check if rule exists
log_info "Checking if rule exists..."
RULE_STATUS=$(aws events describe-rule \
    --name "$RULE_NAME" \
    --region "$AWS_REGION" \
    --profile "$AWS_PROFILE" \
    --query 'State' \
    --output text 2>/dev/null || echo "NOT_FOUND")

if [ "$RULE_STATUS" = "NOT_FOUND" ]; then
    log_error "Rule '$RULE_NAME' not found"
    echo ""
    echo "Run this to create it:"
    echo "  ./scripts/setup_eventbridge_rule.sh"
    exit 1
fi

log_success "Rule exists and is $RULE_STATUS"

# 2. Get rule details
log_info "Getting rule details..."
RULE_ARN=$(aws events describe-rule \
    --name "$RULE_NAME" \
    --region "$AWS_REGION" \
    --profile "$AWS_PROFILE" \
    --query 'Arn' \
    --output text)

EVENT_PATTERN=$(aws events describe-rule \
    --name "$RULE_NAME" \
    --region "$AWS_REGION" \
    --profile "$AWS_PROFILE" \
    --query 'EventPattern' \
    --output text)

echo ""
echo "Rule ARN:      $RULE_ARN"
echo "Event Pattern: $EVENT_PATTERN"

# 3. Check targets
log_info "Checking targets..."
TARGETS=$(aws events list-targets-by-rule \
    --rule "$RULE_NAME" \
    --region "$AWS_REGION" \
    --profile "$AWS_PROFILE" \
    --query 'Targets[*].[Id,Arn]' \
    --output text)

if [ -z "$TARGETS" ]; then
    log_error "No targets configured for the rule"
    exit 1
fi

echo ""
echo "Targets:"
echo "$TARGETS" | while read id arn; do
    echo "  - ID: $id"
    echo "    ARN: $arn"
done

# 4. Check Lambda permissions
log_info "Checking Lambda permissions..."
LAMBDA_ARN=$(echo "$TARGETS" | head -1 | awk '{print $2}')
LAMBDA_NAME=$(echo "$LAMBDA_ARN" | awk -F: '{print $7}')

PERMISSIONS=$(aws lambda get-policy \
    --function-name "$LAMBDA_NAME" \
    --region "$AWS_REGION" \
    --profile "$AWS_PROFILE" \
    --query 'Policy' \
    --output text 2>/dev/null || echo "{}")

if echo "$PERMISSIONS" | grep -q "events.amazonaws.com"; then
    log_success "Lambda has permission for EventBridge to invoke"
else
    log_error "Lambda missing permission for EventBridge"
    echo "Run: ./scripts/setup_eventbridge_rule.sh"
    exit 1
fi

# 5. Check recent invocations (from CloudWatch Metrics)
log_info "Checking recent rule invocations (last 5 minutes)..."

END_TIME=$(date -u +%Y-%m-%dT%H:%M:%S)
START_TIME=$(date -u -v-5M +%Y-%m-%dT%H:%M:%S 2>/dev/null || date -u -d '5 minutes ago' +%Y-%m-%dT%H:%M:%S)

INVOCATIONS=$(aws cloudwatch get-metric-statistics \
    --namespace AWS/Events \
    --metric-name Invocations \
    --dimensions Name=RuleName,Value="$RULE_NAME" \
    --start-time "$START_TIME" \
    --end-time "$END_TIME" \
    --period 300 \
    --statistics Sum \
    --region "$AWS_REGION" \
    --profile "$AWS_PROFILE" \
    --query 'Datapoints[0].Sum' \
    --output text)

if [ "$INVOCATIONS" = "None" ] || [ -z "$INVOCATIONS" ]; then
    log_info "No invocations in the last 5 minutes"
    echo "  This is normal if no ECS tasks have changed state recently"
else
    log_success "Rule has been invoked $INVOCATIONS times in the last 5 minutes"
fi

# 6. Instructions for testing
echo ""
echo "═══════════════════════════════════════════════════════════════"
log_success "EventBridge rule is properly configured"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "To test it works end-to-end:"
echo ""
echo "1. Create a container:"
echo "   curl -X POST https://prz6mum7c7.execute-api.ap-southeast-2.amazonaws.com/containers \\"
echo "        -H 'Authorization: Bearer YOUR_API_KEY' \\"
echo "        -H 'Content-Type: application/json' \\"
echo "        -d '{\"config_name\": \"default\"}'"
echo ""
echo "2. Check initial status (should be PENDING):"
echo "   curl https://prz6mum7c7.execute-api.ap-southeast-2.amazonaws.com/containers/CONTAINER_ID \\"
echo "        -H 'Authorization: Bearer YOUR_API_KEY'"
echo ""
echo "3. Wait 30-60 seconds for ECS task to start"
echo ""
echo "4. Check status again (should now be RUNNING with IP address):"
echo "   curl https://prz6mum7c7.execute-api.ap-southeast-2.amazonaws.com/containers/CONTAINER_ID \\"
echo "        -H 'Authorization: Bearer YOUR_API_KEY'"
echo ""
echo "5. Check CloudWatch Logs for EventBridge invocations:"
echo "   aws logs tail /aws/lambda/$LAMBDA_NAME --follow --region $AWS_REGION --profile $AWS_PROFILE"
echo ""
