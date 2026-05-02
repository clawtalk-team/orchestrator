# Tailscale integration for the orchestrator Lambda
#
# Provisions:
#   - A reusable, ephemeral, pre-authorised Tailscale auth key tagged
#     "tag:voxhelm"
#   - An SSM SecureString that holds the key so the Lambda can fetch it
#     at cold-start without embedding secrets in the image
#   - An IAM policy granting the Lambda execution role read access to
#     that SSM parameter
#
# Prerequisites (one-time, manual — see docs/DEPLOYMENT.md#tailscale-setup):
#   1. In the Tailscale Admin Console, create an OAuth client with the
#      "devices:write" scope and export the credentials:
#        export TAILSCALE_OAUTH_CLIENT_ID=<id>
#        export TAILSCALE_OAUTH_CLIENT_SECRET=<secret>
#   2. Add "tag:voxhelm" to tagOwners in your tailnet ACL
#      before running `terraform apply` (tagged keys can only be created
#      after the tag is declared).
#
# This file is a module included from ../infrastructure (the root Terraform).
# The root module must declare the tailscale provider:
#
#   terraform {
#     required_providers {
#       tailscale = { source = "tailscale/tailscale", version = "~> 0.17" }
#     }
#   }
#   provider "tailscale" {
#     tailnet = var.tailscale_tailnet
#     # reads TAILSCALE_OAUTH_CLIENT_ID + TAILSCALE_OAUTH_CLIENT_SECRET from env
#   }
#
# After apply, in ../infrastructure:
#   - attach aws_iam_policy.lambda_tailscale_ssm to the Lambda execution role
#   - set TAILSCALE_AUTH_KEY_SSM_PATH = aws_ssm_parameter.tailscale_auth_key.name
#     on the Lambda function environment

# ---------------------------------------------------------------------------
# Tailscale auth key
# ---------------------------------------------------------------------------
# reusable=true  — Lambda cold-starts share one key (no per-instance key needed)
# ephemeral=true — nodes are auto-removed when the Lambda env is recycled,
#                  keeping the Tailscale devices list clean
# preauthorized  — nodes join without manual approval

resource "tailscale_tailnet_key" "lambda_orchestrator" {
  reusable      = true
  ephemeral     = true
  preauthorized = true
  tags          = ["tag:voxhelm"]
  description   = "orchestrator Lambda (${var.environment})"
  expiry        = 7776000 # 90 days; rotate by running terraform apply
}

# ---------------------------------------------------------------------------
# SSM SecureString
# ---------------------------------------------------------------------------

resource "aws_ssm_parameter" "tailscale_auth_key" {
  name        = "/clawtalk/orchestrator/${var.environment}/tailscale/auth-key"
  description = "Tailscale auth key for orchestrator Lambda (${var.environment})"
  type        = "SecureString"
  value       = tailscale_tailnet_key.lambda_orchestrator.key

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
  description = "Allow orchestrator Lambda to read its Tailscale auth key from SSM"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadTailscaleAuthKey"
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = aws_ssm_parameter.tailscale_auth_key.arn
      },
      {
        Sid    = "DecryptSSMKMS"
        Effect = "Allow"
        Action = ["kms:Decrypt"]
        # Scoped to SSM in this region only
        Resource = "*"
        Condition = {
          StringEquals = {
            "kms:ViaService" = "ssm.${var.aws_region}.amazonaws.com"
          }
        }
      }
    ]
  })

  tags = {
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------

variable "tailscale_tailnet" {
  description = "Tailscale tailnet name (e.g. example.com or org-name.github)"
  type        = string
}

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

output "tailscale_auth_key_ssm_path" {
  description = "Set TAILSCALE_AUTH_KEY_SSM_PATH on the Lambda function to this value"
  value       = aws_ssm_parameter.tailscale_auth_key.name
}

output "lambda_tailscale_policy_arn" {
  description = "Attach this policy to the Lambda execution role"
  value       = aws_iam_policy.lambda_tailscale_ssm.arn
  sensitive   = false
}
