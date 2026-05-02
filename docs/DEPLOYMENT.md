# Deployment Guide

## Prerequisites

- AWS CLI configured with `--profile personal`
- Docker with ARM64 support (for Lambda)
- Terraform 1.5+
- Access to ECR repository: `826182175287.dkr.ecr.ap-southeast-2.amazonaws.com/orchestrator`

## Build & Deploy

### 1. Build Docker Image

```bash
# Build ARM64 Lambda image
IMAGE_TAG=$(git rev-parse --short HEAD)
docker buildx build \
  --provenance=false \
  --sbom=false \
  --load \
  --platform linux/arm64 \
  --build-arg GIT_COMMIT=${IMAGE_TAG} \
  -f Dockerfile.lambda \
  -t 826182175287.dkr.ecr.ap-southeast-2.amazonaws.com/orchestrator:dev-latest \
  .

# Login to ECR
aws --profile personal ecr get-login-password --region ap-southeast-2 | \
  docker login --username AWS --password-stdin \
  826182175287.dkr.ecr.ap-southeast-2.amazonaws.com

# Push image
docker push 826182175287.dkr.ecr.ap-southeast-2.amazonaws.com/orchestrator:dev-latest
```

### 2. Deploy Infrastructure

```bash
cd ../infrastructure/infra/environments/dev

# Initialize Terraform
terraform init

# Plan deployment
terraform plan -var="orchestrator_image_tag=dev-latest"

# Apply changes
terraform apply -auto-approve -var="orchestrator_image_tag=dev-latest"
```

### 3. Verify Deployment

```bash
# Get API URL from Terraform outputs
terraform output orchestrator_url

# Test health endpoint
curl $(terraform output -raw orchestrator_url)/health

# Create test container
curl -X POST $(terraform output -raw orchestrator_url)/containers \
  -H "Authorization: Bearer {USER_ID}:{YOUR_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{}'
```

## Update Deployment

### Update Code Only

```bash
# Rebuild and push image
IMAGE_TAG=$(git rev-parse --short HEAD)
docker buildx build --provenance=false --sbom=false --load --platform linux/arm64 \
  --build-arg GIT_COMMIT=${IMAGE_TAG} -f Dockerfile.lambda \
  -t 826182175287.dkr.ecr.ap-southeast-2.amazonaws.com/orchestrator:dev-latest .
docker push 826182175287.dkr.ecr.ap-southeast-2.amazonaws.com/orchestrator:dev-latest

# Update Lambda function
aws --profile personal lambda update-function-code \
  --function-name orchestrator-dev \
  --region ap-southeast-2 \
  --image-uri 826182175287.dkr.ecr.ap-southeast-2.amazonaws.com/orchestrator:dev-latest
```

### Update Infrastructure

```bash
cd ../infrastructure/infra/environments/dev
terraform apply -auto-approve -var="orchestrator_image_tag=dev-latest"
```

## Monitoring & Logs

### View Lambda Logs

```bash
# Tail recent logs
aws --profile personal logs tail /aws/lambda/orchestrator-dev \
  --region ap-southeast-2 \
  --since 10m \
  --follow

# Filter for errors
aws --profile personal logs tail /aws/lambda/orchestrator-dev \
  --region ap-southeast-2 \
  --since 1h \
  --filter-pattern "ERROR"
```

### View Container Logs

```bash
# Get container details from API
CONTAINER_ID="{CONTAINER_ID}"
curl https://prz6mum7c7.execute-api.ap-southeast-2.amazonaws.com/containers/${CONTAINER_ID} \
  -H "Authorization: Bearer {USER_ID}:{YOUR_TOKEN}"

# Get task ARN from DynamoDB
USER_ID="{USER_ID}"
TASK_ARN=$(aws --profile personal dynamodb get-item \
  --table-name openclaw-containers-dev \
  --region ap-southeast-2 \
  --key '{"pk":{"S":"USER#'${USER_ID}'"},"sk":{"S":"CONTAINER#'${CONTAINER_ID}'"}}' \
  --query 'Item.task_arn.S' \
  --output text)

# Extract task ID from ARN
TASK_ID=$(echo $TASK_ARN | rev | cut -d'/' -f1 | rev)

# View container logs (openclaw-agent)
aws --profile personal logs tail /ecs/openclaw-agent-dev \
  --region ap-southeast-2 \
  --since 30m \
  --format short \
  --filter-pattern "$TASK_ID"

# Follow logs in real-time
aws --profile personal logs tail /ecs/openclaw-agent-dev \
  --region ap-southeast-2 \
  --follow \
  --format short
```

### Check ECS Task Status

```bash
# List running tasks
aws --profile personal ecs list-tasks \
  --cluster clawtalk-dev \
  --region ap-southeast-2 \
  --desired-status RUNNING

# Describe specific task
aws --profile personal ecs describe-tasks \
  --cluster clawtalk-dev \
  --region ap-southeast-2 \
  --tasks $TASK_ARN \
  --query 'tasks[0].{status:lastStatus,ip:containers[0].networkInterfaces[0].privateIpv4Address}'
```

### Query DynamoDB

```bash
# Scan all containers
aws --profile personal dynamodb scan \
  --table-name openclaw-containers-dev \
  --region ap-southeast-2

# Get specific container
aws --profile personal dynamodb get-item \
  --table-name openclaw-containers-dev \
  --region ap-southeast-2 \
  --key '{"pk":{"S":"USER#{USER_ID}"},"sk":{"S":"CONTAINER#{CONTAINER_ID}"}}'
```

## Troubleshooting

### Lambda Permission Errors

If you see "Permission denied" errors, rebuild the Docker image with correct permissions:

```bash
# Dockerfile.lambda includes: RUN chmod -R 755 ${LAMBDA_TASK_ROOT}
docker buildx build --provenance=false --sbom=false --load --platform linux/arm64 \
  -f Dockerfile.lambda \
  -t 826182175287.dkr.ecr.ap-southeast-2.amazonaws.com/orchestrator:dev-latest .
```

### ECS Task Won't Start

Check IAM permissions and network configuration:

```bash
# Verify subnet/security group IDs in Lambda env vars
aws --profile personal lambda get-function-configuration \
  --function-name orchestrator-dev \
  --region ap-southeast-2 \
  --query 'Environment.Variables.{subnets:ECS_SUBNETS,sgs:ECS_SECURITY_GROUPS}'
```

### DynamoDB Status Not Updating

Currently, the orchestrator doesn't have EventBridge integration (Phase 2). Status updates happen:
- On container creation (PENDING)
- Manual status checks would need to query ECS

## Tailscale Setup

The orchestrator Lambda can connect outbound to a [Tailscale](https://tailscale.com) tailnet at cold-start. This is optional — if the environment variable is not set the Lambda starts without it.

### One-time Tailscale Admin Console setup

These steps are manual (done once per tailnet). Everything after this is managed by Terraform.

#### 1. Declare the tag in your ACL

In the [Tailscale Admin Console](https://login.tailscale.com/admin/acls) → **Access Controls**, add the tag and its owner to `tagOwners`. Tailscale requires the tag to exist before a key referencing it can be created.

```jsonc
{
  "tagOwners": {
    // existing tags...
    "tag:voxhelm": ["autogroup:admin"]
  },
  "acls": [
    // existing rules...
    {
      // Allow Lambda nodes to initiate connections to any tailnet host.
      // Tighten the dst list once you know the exact services to reach.
      "action": "accept",
      "src":    ["tag:voxhelm"],
      "dst":    ["*:*"]
    }
  ]
}
```

#### 2. Create an OAuth client for Terraform

In the Tailscale Admin Console → **Settings → OAuth clients**, create a new client with the `devices:write` scope. Note the client ID and secret — Terraform needs them to provision auth keys.

```bash
export TAILSCALE_OAUTH_CLIENT_ID=<client-id>
export TAILSCALE_OAUTH_CLIENT_SECRET=<client-secret>
```

### Deploy Tailscale infrastructure with Terraform

`infrastructure/tailscale.tf` is a module included from the root Terraform in `../infrastructure`. Run it from there:

```bash
cd ../infrastructure/infra/environments/dev

terraform init

# Preview what will be created (Tailscale auth key, SSM parameter, IAM policy)
terraform plan \
  -var="tailscale_tailnet=<your-tailnet>" \
  -var="orchestrator_image_tag=dev-latest"

# Apply
terraform apply \
  -var="tailscale_tailnet=<your-tailnet>" \
  -var="orchestrator_image_tag=dev-latest"
```

`<your-tailnet>` is the organisation name shown in the Tailscale Admin Console
(e.g. `example.com` or `your-org.github`).

The root module must declare the Tailscale provider and pass
`TAILSCALE_OAUTH_CLIENT_ID` / `TAILSCALE_OAUTH_CLIENT_SECRET` via environment variables.

After `apply`, Terraform outputs:

| Output | Description |
|---|---|
| `tailscale_auth_key_ssm_path` | SSM path — use as `TAILSCALE_AUTH_KEY_SSM_PATH` on the Lambda |
| `lambda_tailscale_policy_arn` | IAM policy ARN — attach to the Lambda execution role |

### Wire up the Lambda

In your main infrastructure Terraform (in the `../infrastructure` repo):

1. **Attach the IAM policy** to the Lambda execution role:
   ```hcl
   resource "aws_iam_role_policy_attachment" "orchestrator_tailscale" {
     role       = aws_iam_role.orchestrator_lambda.name
     policy_arn = "<lambda_tailscale_policy_arn output>"
   }
   ```

2. **Set the environment variable** on the Lambda function:
   ```hcl
   environment {
     variables = {
       TAILSCALE_AUTH_KEY_SSM_PATH = "/clawtalk/orchestrator/dev/tailscale/auth-key"
     }
   }
   ```

Or update the Lambda manually:
```bash
aws --profile personal lambda update-function-configuration \
  --function-name orchestrator-dev \
  --region ap-southeast-2 \
  --environment "Variables={TAILSCALE_AUTH_KEY_SSM_PATH=/clawtalk/orchestrator/dev/tailscale/auth-key}"
```

### Rotate the auth key

The Tailscale auth key expires after 90 days. To rotate:

```bash
cd infrastructure
terraform apply \
  -var="tailscale_tailnet=<your-tailnet>" \
  -var="environment=dev" \
  -replace="tailscale_tailnet_key.lambda_orchestrator"
```

Terraform creates a new key, updates SSM, and the next Lambda cold-start picks it up automatically.

### Verify Tailscale connectivity

After deploying, invoke the Lambda and check CloudWatch Logs for the Tailscale startup messages:

```bash
aws --profile personal logs tail /aws/lambda/orchestrator-dev \
  --region ap-southeast-2 \
  --since 5m \
  --filter-pattern "[tailscale]"
```

Expected output on a successful cold-start:
```
[tailscale] fetching auth key from SSM: /clawtalk/orchestrator/dev/tailscale/auth-key
[tailscale] starting tailscaled (userspace networking)
[tailscale] connecting as orchestrator-lambda-orchestrator-dev
[tailscale] connected to tailnet
```

The node will appear in your Tailscale Admin Console device list tagged as `tag:voxhelm`. It disappears automatically when the Lambda execution environment is recycled.

---

## Clean Up

```bash
# Delete all containers (via API)
for id in $(curl -s https://prz6mum7c7.execute-api.ap-southeast-2.amazonaws.com/containers \
  -H "Authorization: Bearer {USER_ID}:{YOUR_TOKEN}" | jq -r '.[].container_id'); do
  curl -X DELETE https://prz6mum7c7.execute-api.ap-southeast-2.amazonaws.com/containers/$id \
    -H "Authorization: Bearer {USER_ID}:{YOUR_TOKEN}"
done

# Destroy infrastructure (from ../infrastructure/infra/environments/dev)
terraform destroy -auto-approve
```
