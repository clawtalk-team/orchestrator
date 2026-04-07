# EventBridge rule to capture ECS task state changes
# and trigger the orchestrator Lambda function

resource "aws_cloudwatch_event_rule" "ecs_task_state_change" {
  name        = "orchestrator-ecs-task-state-change"
  description = "Capture ECS task state changes for orchestrator to update DynamoDB"

  event_pattern = jsonencode({
    source      = ["aws.ecs"]
    detail-type = ["ECS Task State Change"]
    detail = {
      clusterArn = [var.ecs_cluster_arn]
      lastStatus = ["RUNNING", "STOPPED", "STOPPING"]
    }
  })

  tags = {
    Name        = "orchestrator-ecs-task-state-change"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_cloudwatch_event_target" "orchestrator_lambda" {
  rule      = aws_cloudwatch_event_rule.ecs_task_state_change.name
  target_id = "OrchestratorLambda"
  arn       = var.lambda_function_arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = var.lambda_function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.ecs_task_state_change.arn
}

# Variables
variable "ecs_cluster_arn" {
  description = "ARN of the ECS cluster to monitor"
  type        = string
}

variable "lambda_function_arn" {
  description = "ARN of the orchestrator Lambda function"
  type        = string
}

variable "lambda_function_name" {
  description = "Name of the orchestrator Lambda function"
  type        = string
}

variable "environment" {
  description = "Environment name (dev, prod, etc.)"
  type        = string
  default     = "dev"
}

# Outputs
output "eventbridge_rule_arn" {
  description = "ARN of the EventBridge rule"
  value       = aws_cloudwatch_event_rule.ecs_task_state_change.arn
}

output "eventbridge_rule_name" {
  description = "Name of the EventBridge rule"
  value       = aws_cloudwatch_event_rule.ecs_task_state_change.name
}
