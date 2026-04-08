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
  -H "Authorization: Bearer {USER_ID}:{YOUR_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{}'

# List containers
curl https://prz6mum7c7.execute-api.ap-southeast-2.amazonaws.com/containers \
  -H "Authorization: Bearer {USER_ID}:{YOUR_TOKEN}"

# Get specific container
curl https://prz6mum7c7.execute-api.ap-southeast-2.amazonaws.com/containers/{CONTAINER_ID} \
  -H "Authorization: Bearer {USER_ID}:{YOUR_TOKEN}"

# Delete container
curl -X DELETE https://prz6mum7c7.execute-api.ap-southeast-2.amazonaws.com/containers/{CONTAINER_ID} \
  -H "Authorization: Bearer {USER_ID}:{YOUR_TOKEN}"
```

**Token Format:** `user_id:token_string` (minimum 20 characters total)
Example: `{USER_ID}:{YOUR_TOKEN}`

### Local Development
```bash
# Run locally with Docker Compose
make docker-up

# Test the API
curl http://localhost:8000/health

# Create a container
curl -X POST http://localhost:8000/containers \
  -H "Authorization: Bearer {USER_ID}:{YOUR_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"name": "my-agent"}'
```

## Getting Container Logs

### Quick Method (using container ID)

```bash
CONTAINER_ID="{CONTAINER_ID}"
USER_ID="{USER_ID}"

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

See [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md) for complete deployment and monitoring guide.

## API Endpoints

### Interactive API Documentation

- `GET /docs` - Swagger UI with built-in authentication (click "Authorize" button to enter your API key)
- `GET /redoc` - ReDoc API documentation

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
- Example: `Bearer {USER_ID}:{YOUR_TOKEN}`

Phase 2 will integrate with auth-gateway for full validation.

## Architecture

Built with:
- **FastAPI** - Modern Python API framework
- **AWS Lambda** - Serverless compute (ARM64)
- **API Gateway HTTP API** - HTTP endpoint
- **DynamoDB** - Container metadata and configuration storage
- **ECS Fargate** - Container runtime
- **CloudWatch Logs** - Logging

See [docs/IMPLEMENTATION_SUMMARY.md](./docs/IMPLEMENTATION_SUMMARY.md) for implementation details.

## Documentation

Comprehensive documentation is available in the [`docs/`](./docs/) directory:

- **[Getting Started](./docs/README.md)** - Documentation index
- **[Deployment Guide](./docs/DEPLOYMENT.md)** - Deploy to AWS infrastructure
- **[E2E Testing](./docs/E2E_TEST_GUIDE.md)** - Run end-to-end tests
- **[Implementation Summary](./docs/IMPLEMENTATION_SUMMARY.md)** - Technical implementation details
- **[Container Requirements](./docs/CONTAINER_REQUIREMENTS.md)** - Container configuration requirements

## Development

```bash
# Install dependencies
make install-dev

# Run tests
make test

# Run E2E tests
make test-e2e           # Local with DynamoDB Local
make test-e2e-aws       # Against real AWS DynamoDB

# Run locally
make docker-up

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