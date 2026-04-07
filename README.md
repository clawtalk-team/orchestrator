# Orchestrator Service

Container orchestrator for managing openclaw-agent instances. Provides API for dynamic provisioning, lifecycle management, and health monitoring of containerized agents running on AWS ECS Fargate.

## Overview

The orchestrator enables users to spin up isolated openclaw-agent containers on-demand, each with their own configuration and resources. Built as a serverless FastAPI Lambda function with API Gateway frontend.

## Deployment Status

**✅ Deployed to AWS Dev Environment**

- **API Gateway URL:** `https://prz6mum7c7.execute-api.ap-southeast-2.amazonaws.com/`
- **Lambda Function:** `orchestrator-dev`
- **DynamoDB Table:** `openclaw-containers-dev`
- **Region:** ap-southeast-2

## Quick Start

### Production API (AWS Dev)
```bash
# Health check
curl https://prz6mum7c7.execute-api.ap-southeast-2.amazonaws.com/health

# Create a container
curl -X POST https://prz6mum7c7.execute-api.ap-southeast-2.amazonaws.com/containers \
  -H "Authorization: Bearer andrew:my-super-secret-token-12345" \
  -H "Content-Type: application/json" \
  -d '{}'

# List containers
curl https://prz6mum7c7.execute-api.ap-southeast-2.amazonaws.com/containers \
  -H "Authorization: Bearer andrew:my-super-secret-token-12345"

# Get specific container
curl https://prz6mum7c7.execute-api.ap-southeast-2.amazonaws.com/containers/oc-18c03ca7 \
  -H "Authorization: Bearer andrew:my-super-secret-token-12345"

# Delete container
curl -X DELETE https://prz6mum7c7.execute-api.ap-southeast-2.amazonaws.com/containers/oc-18c03ca7 \
  -H "Authorization: Bearer andrew:my-super-secret-token-12345"
```

**Token Format:** `user_id:token_string` (minimum 20 characters total)
Example: `andrew:my-super-secret-token-12345`

### Local Development
```bash
# Run locally with Docker Compose
make dev

# Test the API
curl http://localhost:8000/health

# Create a container
curl -X POST http://localhost:8000/containers \
  -H "Authorization: Bearer user-123:test-token-abcdefghijklmnop" \
  -H "Content-Type: application/json" \
  -d '{"name": "my-agent"}'
```

## Getting Container Logs

### Quick Method (using container ID)

```bash
CONTAINER_ID="oc-18c03ca7"
USER_ID="andrew"

# 1. Get task ARN from DynamoDB
TASK_ARN=$(aws --profile personal dynamodb get-item \
  --table-name openclaw-containers-dev \
  --region ap-southeast-2 \
  --key "{\"pk\":{\"S\":\"USER#${USER_ID}\"},\"sk\":{\"S\":\"CONTAINER#${CONTAINER_ID}\"}}" \
  --query 'Item.task_arn.S' \
  --output text)

# 2. Extract task ID
TASK_ID=$(echo $TASK_ARN | rev | cut -d'/' -f1 | rev)

# 3. View logs
aws --profile personal logs tail /ecs/openclaw-agent-dev \
  --region ap-southeast-2 \
  --since 30m \
  --format short \
  --filter-pattern "$TASK_ID"

# 4. Follow logs in real-time
aws --profile personal logs tail /ecs/openclaw-agent-dev \
  --region ap-southeast-2 \
  --follow \
  --format short
```

### All Container Logs (recent)

```bash
# View all openclaw-agent logs from last 30 minutes
aws --profile personal logs tail /ecs/openclaw-agent-dev \
  --region ap-southeast-2 \
  --since 30m \
  --follow
```

See [DEPLOYMENT.md](./DEPLOYMENT.md) for complete deployment and monitoring guide.

## API Endpoints

### Container Management

- `POST /containers` - Create new container
- `GET /containers` - List user's containers
- `GET /containers/{id}` - Get container details
- `DELETE /containers/{id}` - Stop and remove container
- `GET /containers/{id}/health` - Get container health status

### System

- `GET /health` - Service health check

## Authentication

Phase 1 uses simple token validation:
- Format: `Bearer user_id:token_hash`
- Minimum length: 20 characters
- Example: `Bearer andrew:my-super-secret-token-12345`

Phase 2 will integrate with auth-gateway for full validation.

## Architecture

Built with:
- **FastAPI** - Modern Python API framework
- **AWS Lambda** - Serverless compute (ARM64)
- **API Gateway HTTP API** - HTTP endpoint
- **DynamoDB** - Container metadata persistence
- **ECS Fargate** - Container runtime
- **CloudWatch Logs** - Logging

See [ARCHITECTURE_PLAN.md](./ARCHITECTURE_PLAN.md) for detailed architecture documentation.

## Development

```bash
# Install dependencies
make install-dev

# Run tests
make test

# Run locally
make dev

# Build Lambda image
make build-lambda

# Deploy to AWS
cd ../infrastructure/infra/environments/dev
terraform apply -var="orchestrator_image_tag=dev-latest"
```

## Project Structure

```
orchestrator/
├── app/
│   ├── main.py              # FastAPI application
│   ├── config.py            # Settings and configuration
│   ├── middleware/          # Authentication middleware
│   ├── models/              # Pydantic models
│   ├── routes/              # API endpoint handlers
│   └── services/            # Business logic (DynamoDB, ECS)
├── tests/                   # Unit and integration tests
├── lambda_handler.py        # AWS Lambda entry point
├── Dockerfile.lambda        # Lambda container image
└── docker-compose.yml       # Local development setup
```

## License

Proprietary - All rights reserved