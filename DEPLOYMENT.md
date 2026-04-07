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
