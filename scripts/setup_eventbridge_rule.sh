#!/bin/bash
#
# Setup EventBridge rule to capture ECS task state changes
# and trigger the orchestrator Lambda function to update DynamoDB.
#
# Usage:
#   AWS_PROFILE=personal ./scripts/setup_eventbridge_rule.sh
#

set -e

# Configuration
AWS_PROFILE="${AWS_PROFILE:-personal}"
AWS_REGION="${AWS_REGION:-ap-southeast-2}"
CLUSTER_NAME="${ECS_CLUSTER_NAME:-clawtalk-dev}"
LAMBDA_FUNCTION_NAME="${LAMBDA_FUNCTION_NAME:-orchestrator-dev}"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_info "Setting up EventBridge rule for ECS task state changes"
log_info "Cluster: $CLUSTER_NAME"
log_info "Lambda: $LAMBDA_FUNCTION_NAME"
log_info "Region: $AWS_REGION"
log_info "Profile: $AWS_PROFILE"

# 1. Get cluster ARN
log_info "Getting cluster ARN..."
CLUSTER_ARN=$(aws ecs describe-clusters \
    --clusters "$CLUSTER_NAME" \
    --region "$AWS_REGION" \
    --profile "$AWS_PROFILE" \
    --query 'clusters[0].clusterArn' \
    --output text)

if [ -z "$CLUSTER_ARN" ] || [ "$CLUSTER_ARN" = "None" ]; then
    log_error "Cluster '$CLUSTER_NAME' not found"
    exit 1
fi
log_success "Cluster ARN: $CLUSTER_ARN"

# 2. Get Lambda function ARN
log_info "Getting Lambda function ARN..."
LAMBDA_ARN=$(aws lambda get-function \
    --function-name "$LAMBDA_FUNCTION_NAME" \
    --region "$AWS_REGION" \
    --profile "$AWS_PROFILE" \
    --query 'Configuration.FunctionArn' \
    --output text)

if [ -z "$LAMBDA_ARN" ] || [ "$LAMBDA_ARN" = "None" ]; then
    log_error "Lambda function '$LAMBDA_FUNCTION_NAME' not found"
    exit 1
fi
log_success "Lambda ARN: $LAMBDA_ARN"

# 3. Create EventBridge rule
RULE_NAME="orchestrator-ecs-task-state-change"
log_info "Creating EventBridge rule: $RULE_NAME"

# Event pattern
EVENT_PATTERN=$(cat <<EOF
{
  "source": ["aws.ecs"],
  "detail-type": ["ECS Task State Change"],
  "detail": {
    "clusterArn": ["$CLUSTER_ARN"],
    "lastStatus": ["RUNNING", "STOPPED", "STOPPING"]
  }
}
EOF
)

aws events put-rule \
    --name "$RULE_NAME" \
    --description "Capture ECS task state changes for orchestrator to update DynamoDB" \
    --event-pattern "$EVENT_PATTERN" \
    --state ENABLED \
    --region "$AWS_REGION" \
    --profile "$AWS_PROFILE" > /dev/null

RULE_ARN=$(aws events describe-rule \
    --name "$RULE_NAME" \
    --region "$AWS_REGION" \
    --profile "$AWS_PROFILE" \
    --query 'Arn' \
    --output text)

log_success "EventBridge rule created: $RULE_ARN"

# 4. Add Lambda permission to allow EventBridge to invoke it
log_info "Adding Lambda permission for EventBridge..."

STATEMENT_ID="AllowEventBridgeInvoke-$RULE_NAME"

# Remove existing permission if it exists
aws lambda remove-permission \
    --function-name "$LAMBDA_FUNCTION_NAME" \
    --statement-id "$STATEMENT_ID" \
    --region "$AWS_REGION" \
    --profile "$AWS_PROFILE" 2>/dev/null || true

# Add permission
aws lambda add-permission \
    --function-name "$LAMBDA_FUNCTION_NAME" \
    --statement-id "$STATEMENT_ID" \
    --action "lambda:InvokeFunction" \
    --principal "events.amazonaws.com" \
    --source-arn "$RULE_ARN" \
    --region "$AWS_REGION" \
    --profile "$AWS_PROFILE" > /dev/null

log_success "Lambda permission added"

# 5. Add Lambda as target of the EventBridge rule
log_info "Adding Lambda as target..."

aws events put-targets \
    --rule "$RULE_NAME" \
    --targets "Id=1,Arn=$LAMBDA_ARN" \
    --region "$AWS_REGION" \
    --profile "$AWS_PROFILE" > /dev/null

log_success "Lambda target added"

# 6. Verify setup
log_info "Verifying setup..."

RULE_STATUS=$(aws events describe-rule \
    --name "$RULE_NAME" \
    --region "$AWS_REGION" \
    --profile "$AWS_PROFILE" \
    --query 'State' \
    --output text)

TARGETS=$(aws events list-targets-by-rule \
    --rule "$RULE_NAME" \
    --region "$AWS_REGION" \
    --profile "$AWS_PROFILE" \
    --query 'Targets[*].Arn' \
    --output text)

echo ""
echo "═══════════════════════════════════════════════════════════════"
log_success "EventBridge rule setup complete!"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "Rule Name:    $RULE_NAME"
echo "Rule ARN:     $RULE_ARN"
echo "Rule State:   $RULE_STATUS"
echo "Target:       $LAMBDA_ARN"
echo ""
echo "The rule will trigger when ECS tasks in cluster '$CLUSTER_NAME'"
echo "reach status: RUNNING, STOPPED, or STOPPING"
echo ""
log_info "Next steps:"
echo "  1. Create a new container to test: POST /containers"
echo "  2. Wait for task to reach RUNNING state"
echo "  3. Check DynamoDB updates: GET /containers/{container_id}"
echo "  4. Verify status changes from PENDING to RUNNING"
echo ""
