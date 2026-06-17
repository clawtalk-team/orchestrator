# Tailscale integration for the orchestrator Lambda
#
# Provisions:
#   - An SSM SecureString slot for the Tailscale personal API key
#     (value is set manually — see docs/DEPLOYMENT.md#tailscale-setup)
#   - An IAM policy granting the Lambda execution role read access to
#     that parameter
#
# How rotation works
# ------------------
# The Lambda does NOT store a long-lived auth key. On every cold start,
# scripts/lambda-entrypoint.sh reads the API key from SSM and calls the
# Tailscale API to mint a fresh single-use ephemeral auth key (5-min TTL).
# This means:
#   - Auth keys never need rotation — they're generated on demand and
#     discarded after use.
#   - The API key in SSM needs updating every 90 days (Tailscale's max
#     expiry). This is a single `aws ssm put-parameter` call; no Terraform
#     change or deployment is required.
#
# New environment checklist (see docs/DEPLOYMENT.md#tailscale-setup):
#   1. Ensure "tag:orchestrator" exists in your tailnet ACL tagOwners
#   2. Generate a Tailscale API key (Settings → Keys, set max 90-day expiry)
#   3. Run: aws ssm put-parameter --name <path> --type SecureString --value <key>
#   4. Apply this module (creates the SSM slot if it doesn't exist yet)
#   5. Attach the output IAM policy to the Lambda execution role
#   6. Set TAILSCALE_API_KEY_SSM_PATH on the Lambda function
#
# This file is a module included from ../infrastructure (the root Terraform).

# ---------------------------------------------------------------------------
# SSM SecureString — Tailscale personal API key
# ---------------------------------------------------------------------------
# Terraform creates the parameter slot with a placeholder.
# Populate with the real API key before deploying the Lambda:
#
#   aws ssm put-parameter \
#     --name "/clawtalk/orchestrator/<env>/tailscale/api-key" \
#     --type SecureString \
#     --value "tskey-api-..." \
#     --overwrite
#
# lifecycle.ignore_changes = [value] ensures Terraform never overwrites a
# key that has already been set.

resource "aws_ssm_parameter" "tailscale_api_key" {
  name        = "/clawtalk/orchestrator/${var.environment}/tailscale/api-key"
  description = "Tailscale personal API key for orchestrator Lambda dynamic key generation (${var.environment}). Rotate every 90 days."
  type        = "SecureString"
  value       = "REPLACE_ME"

  lifecycle {
    ignore_changes = [value]
  }

  tags = {
    Environment = var.environment
    ManagedBy   = "terraform"
    Service     = "orchestrator"
  }
}

# ---------------------------------------------------------------------------
# IAM policy — Lambda execution role must have this attached
# ---------------------------------------------------------------------------

resource "aws_iam_policy" "lambda_tailscale_ssm" {
  name        = "orchestrator-tailscale-ssm-${var.environment}"
  description = "Allow orchestrator Lambda to read its Tailscale API key from SSM"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "ReadTailscaleApiKey"
      Effect   = "Allow"
      Action   = ["ssm:GetParameter"]
      Resource = aws_ssm_parameter.tailscale_api_key.arn
    }]
  })

  tags = {
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------

variable "environment" {
  description = "Environment name (dev, prod, etc.)"
  type        = string
  default     = "dev"
}

variable "aws_region" {
  description = "AWS region where the orchestrator Lambda runs"
  type        = string
  default     = "ap-southeast-2"
}

# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

output "tailscale_api_key_ssm_path" {
  description = "Set TAILSCALE_API_KEY_SSM_PATH on the Lambda function to this value"
  value       = aws_ssm_parameter.tailscale_api_key.name
}

output "lambda_tailscale_policy_arn" {
  description = "Attach this policy to the Lambda execution role"
  value       = aws_iam_policy.lambda_tailscale_ssm.arn
}
