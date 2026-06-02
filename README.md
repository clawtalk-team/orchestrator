# Orchestrator Service

Container orchestrator for managing openclaw-agent instances. Provides API for dynamic provisioning, lifecycle management, and health monitoring of containerized agents running on AWS ECS Fargate or Kubernetes.

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

### Configuration Management

- `GET /config` - List all user configurations
- `POST /config` - Create a new user configuration
- `GET /config/{config_name}` - Get a specific user configuration
- `PUT /config/{config_name}` - Update a user configuration (merge or overwrite)
- `DELETE /config/{config_name}` - Delete a user configuration
- `GET /config/system` - Get system-wide configuration (admin only)
- `PUT /config/system` - Update system-wide configuration (admin only)

### System

- `GET /health` - Service health check

## Authentication

Phase 1 uses simple token validation:
- Format: `Bearer user_id:token_hash`
- Minimum length: 20 characters
- Example: `Bearer {USER_ID}:{YOUR_TOKEN}`

Phase 2 will integrate with auth-gateway for full validation.

## Configuration System

The orchestrator uses a **two-tier configuration system** that separates infrastructure-wide settings from user-specific preferences.

### Configuration Hierarchy

For system-level fields (`auth_gateway_url`, `openclaw_url`, `openclaw_token`, `voice_gateway_url`):

```
System Config (always wins for system-level fields)
  ↓
User Config (user-specific fields only: API keys, model preferences)
  ↓
Hardcoded Defaults (fallback)
```

### How It Works

When a container is created, the orchestrator:
1. Saves the user's auth key into their user config in DynamoDB
2. Creates a DynamoDB record for the container in `PENDING` status
3. Launches a container (ECS task or Kubernetes Pod) with a small set of bootstrap environment variables (see below)

> **Note:** `ip_address` is not required at this stage. On ECS it is populated asynchronously via an EventBridge task-state event when the task reaches `RUNNING`; on Kubernetes it is synced by a scheduled EventBridge poller (every 60 s) as well as on any `GET /containers/{id}` call. Its absence does not affect container functionality — the container communicates outbound via the orchestrator URL injected at launch time.

At startup, the container's `openclaw-agent --init` fetches config from the orchestrator API, builds `~/.openclaw/openclaw.json` and `~/.clawtalk/clawtalk.json`, then starts `openclaw-agent`.

This ensures:
- Admins can update infrastructure URLs globally without recreating containers
- Users maintain their own API keys and preferences
- The config files on disk always reflect the state of DynamoDB at container start time

### Compute Backends

The orchestrator supports two compute backends, selectable per-request or via server default:

| Backend | Description |
|---------|-------------|
| `ecs` | AWS ECS Fargate — serverless tasks, managed by AWS |
| `k8s` | Kubernetes — pods on a self-managed or cloud-managed cluster |

The **server default** is controlled by the `DEFAULT_BACKEND` environment variable (e.g. `DEFAULT_BACKEND=k8s`). Individual container creation requests can override it by including `"backend": "k8s"` or `"backend": "ecs"` in the request body. Once created, a container's backend is stored in DynamoDB and all subsequent operations (status, delete) route to the correct backend automatically.

### Container Environment Variables

These variables are injected at creation time (same set for both ECS and Kubernetes):

| Variable | Value | Description |
|---|---|---|
| `API_KEY` | From `Authorization` header | User's auth-gateway API key |
| `CONTAINER_ID` | Generated ID | Identifies this container |
| `CONFIG_NAME` | Request param (default: `default`) | Which named config to load |
| `ORCHESTRATOR_URL` | `settings.orchestrator_url` | URL of this orchestrator service |
| `AGENT_ID` | Request param (if supplied) | Agent ID to register at startup |
| `OPENCLAW_DISABLE_BONJOUR` | `1` | Disables mDNS/Bonjour discovery |
| `OPENROUTER_API_KEY` | From user config (if set) | OpenRouter API key |
| `ANTHROPIC_API_KEY` | From user config (if set) | Anthropic API key |
| `OPENAI_API_KEY` | From user config (if set) | OpenAI API key |

The keys `API_KEY`, `CONTAINER_ID`, `CONFIG_NAME`, `ORCHESTRATOR_URL`, `AGENT_ID`, and `OPENCLAW_DISABLE_BONJOUR` are **protected** and cannot be overridden by caller-supplied `env_vars`.

### System Configuration (Admin-managed)

System configs define infrastructure shared by all users:

| Parameter | Type | Description | Example |
|-----------|------|-------------|---------|
| `auth_gateway_url` | string | Auth gateway endpoint URL | `https://z1fm1cdkph.execute-api.ap-southeast-2.amazonaws.com` |
| `openclaw_url` | string | OpenClaw gateway URL | `http://localhost:18789` |
| `openclaw_token` | string | Shared OpenClaw service token | `test-token-123` |
| `voice_gateway_url` | string | Voice gateway WebSocket URL | `ws://localhost:9090` |

**Storage location:** DynamoDB key `pk="SYSTEM"`, `sk="CONFIG#defaults"`

### User Configuration (User-specific)

User configs define personal settings and secrets:

| Parameter | Type | Description | Example | Required |
|-----------|------|-------------|---------|----------|
| `llm_provider` | string | LLM provider choice | `anthropic`, `openai`, `openrouter` | Yes |
| `openclaw_model` | string | Default model to use | `claude-3-haiku-20240307` | Yes |
| `auth_gateway_api_key` | string | User's auth gateway API key | `b13b7bb9cbe9ecfa112cf...` | Yes |
| `anthropic_api_key` | string | Anthropic API key (if provider=anthropic) | `sk-ant-api03-...` | Conditional |
| `openai_api_key` | string | OpenAI API key (if provider=openai) | `sk-...` | Conditional |
| `openrouter_api_key` | string | OpenRouter API key (if provider=openrouter) | `sk-or-...` | Conditional |

**Storage location:** DynamoDB key `pk="USER#{user_id}"`, `sk="CONFIG#{config_name}"`

**Note:** This parameter set will grow as new features are added (e.g., voice settings, agent preferences, custom models).

### Setting Up Default Configurations

#### Option 1: Using the Helper Script (Recommended)

```bash
# Load system + user defaults
python3 scripts/load_defaults.py \
  --system \
  --user-id "your-user-id" \
  --auth-gateway-url "https://z1fm1cdkph.execute-api.ap-southeast-2.amazonaws.com" \
  --openclaw-url "http://localhost:18789" \
  --openclaw-token "test-token-123" \
  --llm-provider "anthropic" \
  --openclaw-model "claude-3-haiku-20240307" \
  --auth-gateway-api-key "your-auth-key" \
  --anthropic-api-key "your-anthropic-key"

# Verify configs were loaded
python3 scripts/load_defaults.py --verify --user-id "your-user-id"
```

#### Option 2: Using the Config API

```bash
# Create/update system config (admin only)
curl -X PUT https://prz6mum7c7.execute-api.ap-southeast-2.amazonaws.com/config/system \
  -H "Authorization: Bearer {ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "auth_gateway_url": "https://z1fm1cdkph.execute-api.ap-southeast-2.amazonaws.com",
    "openclaw_url": "http://localhost:18789",
    "openclaw_token": "test-token-123"
  }'

# Create/update user config
curl -X POST https://prz6mum7c7.execute-api.ap-southeast-2.amazonaws.com/config \
  -H "Authorization: Bearer {USER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "config_name": "default",
    "llm_provider": "anthropic",
    "anthropic_api_key": "sk-ant-...",
    "openclaw_model": "claude-3-haiku-20240307"
  }'
```

#### Option 3: Manual DynamoDB Setup

```python
import boto3
from datetime import datetime, timezone

dynamodb = boto3.resource('dynamodb', region_name='ap-southeast-2')
table = dynamodb.Table('openclaw-containers')

# System config
table.put_item(Item={
    'pk': 'SYSTEM',
    'sk': 'CONFIG#defaults',
    'config_type': 'system_config',
    'auth_gateway_url': 'https://z1fm1cdkph.execute-api.ap-southeast-2.amazonaws.com',
    'openclaw_url': 'http://localhost:18789',
    'openclaw_token': 'test-token-123',
    'voice_gateway_url': 'ws://localhost:9090',
    'updated_at': datetime.now(timezone.utc).isoformat()
})

# User config
table.put_item(Item={
    'pk': 'USER#your-user-id',
    'sk': 'CONFIG#default',
    'config_type': 'user_config',
    'user_id': 'your-user-id',
    'llm_provider': 'anthropic',
    'openclaw_model': 'claude-3-haiku-20240307',
    'auth_gateway_api_key': 'your-auth-key',
    'anthropic_api_key': 'sk-ant-...',
    'created_at': datetime.now(timezone.utc).isoformat(),
    'updated_at': datetime.now(timezone.utc).isoformat()
})
```

### Configuration API Endpoints

- `GET /config` - List all user configurations
- `POST /config` - Create a new user configuration
- `GET /config/{config_name}` - Get a specific user configuration
- `PUT /config/{config_name}` - Update a user configuration
- `DELETE /config/{config_name}` - Delete a user configuration
- `GET /config/system` - Get system configuration (admin only)
- `PUT /config/system` - Update system configuration (admin only)

#### `GET /config/{config_name}?merged=true` response fields

The default (`merged=true`) response combines the user config with system config. System-level fields always overwrite any user-supplied values for the same keys.

**From user config** (`USER#{user_id}/CONFIG#{config_name}` in DynamoDB):

| Field | Description |
|---|---|
| `config_name` | Name of this configuration |
| `user_id` | Owner |
| `llm_provider` | LLM provider: `anthropic`, `openai`, or `openrouter` |
| `openclaw_model` | Model name passed to OpenClaw |
| `anthropic_api_key` | Anthropic API key |
| `openai_api_key` | OpenAI API key |
| `openrouter_api_key` | OpenRouter API key |
| `auth_gateway_api_key` | Auth gateway API key (injected at container creation time) |
| `max_containers` | Maximum containers this user may run |
| `created_at` / `updated_at` | ISO 8601 timestamps |

**From system config** (`SYSTEM/CONFIG#defaults` in DynamoDB) — these fields always win:

| Field | Description |
|---|---|
| `auth_gateway_url` | URL of the auth gateway |
| `openclaw_url` | URL of the OpenClaw gateway |
| `openclaw_token` | Shared OpenClaw auth token |
| `voice_gateway_url` | URL of the voice gateway |

Both models use `extra="allow"`, so any additional fields stored in DynamoDB are passed through in the response.

Use `?merged=false` to retrieve only the raw user config without system fields.

See the [API Documentation](./docs/CONFIG_API.md) for detailed endpoint specs.

### Named Configurations

Users can maintain multiple named configurations:

```bash
# Create a "production" config
curl -X POST .../config \
  -d '{"config_name": "production", "llm_provider": "anthropic", ...}'

# Create a "testing" config
curl -X POST .../config \
  -d '{"config_name": "testing", "llm_provider": "openai", ...}'

# Use specific config when creating container
curl -X POST .../containers \
  -d '{"config_name": "production"}'
```

### How Configs Are Merged

When `GET /config/{config_name}?merged=true` is called (the default), the orchestrator applies `{**user_config, **system_config}` — system config keys always overwrite matching user config keys:

**Example:**

```python
# User Config (from DynamoDB USER#{user_id}/CONFIG#default)
user_config = {
    "llm_provider": "anthropic",
    "anthropic_api_key": "sk-ant-...",
    "openclaw_model": "claude-3-haiku-20240307",
    "auth_gateway_api_key": "b13b7bb9...",
    # Stale value a user may have set previously — will be overwritten:
    "openclaw_url": "http://old-host:18789",
}

# System Config (from DynamoDB SYSTEM/CONFIG#defaults)
system_config = {
    "auth_gateway_url": "https://z1fm1cdkph.execute-api.ap-southeast-2.amazonaws.com",
    "openclaw_url": "http://localhost:18789",  # wins over user's stale value
    "openclaw_token": "test-token-123",
    "voice_gateway_url": "ws://localhost:9090",
}

# Merged result returned by GET /config/{config_name}
merged = {
    # User-specific fields (system config has no opinion on these)
    "llm_provider": "anthropic",
    "anthropic_api_key": "sk-ant-...",
    "openclaw_model": "claude-3-haiku-20240307",
    "auth_gateway_api_key": "b13b7bb9...",

    # System fields — always from system config, stale user value discarded
    "auth_gateway_url": "https://z1fm1cdkph.execute-api.ap-southeast-2.amazonaws.com",
    "openclaw_url": "http://localhost:18789",
    "openclaw_token": "test-token-123",
    "voice_gateway_url": "ws://localhost:9090",
}
```

**Key principle:** System config always wins over user config for system-level fields (`auth_gateway_url`, `openclaw_url`, `openclaw_token`, `voice_gateway_url`). This prevents stale user-config values from overriding live infrastructure config. User-specific fields (API keys, model preferences) are unaffected since they don't exist in the system config.

## Networking — Tailscale

The Lambda container can join a [Tailscale](https://tailscale.com) tailnet on cold-start, giving it outbound access to private services (e.g. an internal OpenClaw gateway or auth service) without a VPN or VPC peering.

Tailscale runs in **userspace-networking** mode (`--tun=userspace-networking`) so no kernel TUN module is required — it works inside Lambda containers out of the box.

### How it works

1. On container start, `scripts/lambda-entrypoint.sh` runs before the Lambda runtime.
2. It reads a Tailscale personal API key from SSM Parameter Store.
3. It calls the Tailscale API to mint a fresh single-use ephemeral auth key (5-minute TTL).
4. It starts `tailscaled` in the background and calls `tailscale up` with the ephemeral key.
5. The Lambda runtime then starts; every outbound call it makes can reach Tailscale nodes.

Lambda execution environments are recycled automatically — because the auth key is `ephemeral=true`, the Tailscale node is cleaned up from the device list when the environment is torn down. Auth keys are never reused and never need rotation.

### Environment variables

| Variable | Required | Description |
|---|---|---|
| `TAILSCALE_API_KEY_SSM_PATH` | Yes (prod) | SSM SecureString path holding a Tailscale personal API key — used to generate fresh ephemeral auth keys on each cold-start |
| `TAILSCALE_AUTH_KEY` | Dev only | Literal auth key; overrides SSM lookup |

If neither variable is set the Lambda starts normally without connecting to Tailscale.

### Setup

See [docs/DEPLOYMENT.md#tailscale-setup](./docs/DEPLOYMENT.md#tailscale-setup) for full one-time setup and Terraform instructions.

## Architecture

Built with:
- **FastAPI** - Modern Python API framework
- **AWS Lambda** - Serverless compute (ARM64)
- **API Gateway HTTP API** - HTTP endpoint
- **DynamoDB** - Container metadata and configuration storage
- **ECS Fargate** - Container runtime (default for production)
- **Kubernetes** - Alternative container runtime (configurable via `DEFAULT_BACKEND=k8s`)
- **CloudWatch Logs** - Logging
- **Tailscale** - Outbound private network connectivity (userspace, optional)

See [docs/IMPLEMENTATION_SUMMARY.md](./docs/IMPLEMENTATION_SUMMARY.md) for implementation details.

## Documentation

Comprehensive documentation is available in the [`docs/`](./docs/) directory:

- **[Getting Started](./docs/README.md)** - Documentation index
- **[Deployment Guide](./docs/DEPLOYMENT.md)** - Deploy to AWS infrastructure
- **[E2E Testing](./docs/E2E_TEST_GUIDE.md)** - Run end-to-end tests
- **[Implementation Summary](./docs/IMPLEMENTATION_SUMMARY.md)** - Technical implementation details
- **[Container Requirements](./docs/CONTAINER_REQUIREMENTS.md)** - Container configuration requirements

## Kubernetes Configuration

When `DEFAULT_BACKEND=k8s` (or a request specifies `"backend": "k8s"`), the orchestrator creates Kubernetes Pods instead of ECS tasks. The following environment variables configure the k8s backend:

| Variable | Default | Description |
|----------|---------|-------------|
| `DEFAULT_BACKEND` | `k8s` | Compute backend to use when not specified per-request (`ecs` or `k8s`) |
| `K8S_NAMESPACE` | `openclaw` | Kubernetes namespace where pods are created |
| `K8S_IMAGE` | `openclaw-agent:latest` | Container image for agent pods |
| `K8S_IMAGE_PULL_POLICY` | `IfNotPresent` | Image pull policy (`Never`, `IfNotPresent`, `Always`) |
| `K8S_IMAGE_PULL_SECRET` | _(none)_ | Name of an `imagePullSecret` for private registries (e.g. `ecr-secret`) |
| `K8S_KUBECONFIG` | _(none)_ | Path to a kubeconfig file. Omit to use in-cluster config or `~/.kube/config` |
| `K8S_KUBECONFIG_SSM_PATH` | _(none)_ | SSM Parameter Store path containing a kubeconfig YAML (takes precedence over `K8S_KUBECONFIG`) |
| `K8S_CONTEXT` | _(current)_ | Kubernetes context to use. Omit to use the current context |

### Kubeconfig Loading Order

1. `K8S_KUBECONFIG_SSM_PATH` — fetch YAML from SSM (SecureString), used when the orchestrator runs in AWS without local file access
2. `K8S_KUBECONFIG` — load from a local file path
3. In-cluster config — used automatically when the orchestrator itself runs inside a Kubernetes pod
4. `~/.kube/config` default — fallback for local development

### Example: Local Development Against a Remote Cluster

```bash
K8S_KUBECONFIG=/path/to/kubeconfig.yaml \
K8S_CONTEXT=my-context \
K8S_IMAGE=826182175287.dkr.ecr.ap-southeast-2.amazonaws.com/openclaw-agent-dev:latest \
K8S_IMAGE_PULL_SECRET=ecr-secret \
K8S_IMAGE_PULL_POLICY=Always \
DEFAULT_BACKEND=k8s \
ORCHESTRATOR_URL=http://<your-tailscale-or-public-ip>:8080 \
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

> **Note:** `ORCHESTRATOR_URL` must be reachable from inside the k8s pods. Use a Tailscale IP, a LoadBalancer address, or an ingress — not `localhost`.

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
│   └── services/            # Business logic (DynamoDB, ECS, Kubernetes)
├── tests/                   # Unit and integration tests
├── lambda_handler.py        # AWS Lambda entry point
├── Dockerfile.lambda        # Lambda container image
└── docker-compose.yml       # Local development setup
```

## License

Proprietary - All rights reserved