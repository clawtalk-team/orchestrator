# Agent Orchestrator

A container orchestration service for dynamically provisioning and managing AI agent instances on **AWS ECS Fargate** or **Kubernetes**. Built as a serverless FastAPI application deployable to AWS Lambda.

## What It Does

The orchestrator gives each user isolated, on-demand agent containers with their own configuration, LLM credentials, and compute resources. It handles the full lifecycle — creation, health monitoring, configuration delivery, and teardown — across both ECS and Kubernetes backends.

**Key capabilities:**

- **Multi-backend** — deploy containers to ECS Fargate or Kubernetes, selectable per-request or via server default
- **Two-tier configuration** — system-wide infrastructure settings (admin-managed) merged with per-user preferences and API keys
- **Named configurations** — users can maintain multiple config profiles (e.g. "production", "testing") and select one at container creation
- **Health monitoring** — track container health, uptime, memory, CPU, and agent status
- **Cluster registry** — admin view of all compute clusters the orchestrator has dispatched to
- **Tailscale integration** — optional outbound private network connectivity from Lambda (userspace networking, no kernel TUN required)
- **Config delivery** — containers bootstrap themselves by fetching merged config from the orchestrator API at startup

While built for [OpenClaw](https://github.com/openclaw) agent containers, the orchestrator can manage any container image that follows its config-delivery protocol.

## Quick Start

### Local Development

```bash
# Install dependencies
make install-dev

# Start local infrastructure (orchestrator + DynamoDB Local)
make docker-up

# Health check
curl http://localhost:8000/health

# Create a container
curl -X POST http://localhost:8000/containers \
  -H "Authorization: Bearer {USER_ID}:{YOUR_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"name": "my-agent"}'

# List containers
curl http://localhost:8000/containers \
  -H "Authorization: Bearer {USER_ID}:{YOUR_TOKEN}"

# Delete a container
curl -X DELETE http://localhost:8000/containers/{CONTAINER_ID} \
  -H "Authorization: Bearer {USER_ID}:{YOUR_TOKEN}"
```

### Running the Server Directly

```bash
make run  # Starts on port 8571
```

## API Endpoints

### Interactive Documentation

- `GET /docs` — Swagger UI (click "Authorize" to enter your API key)
- `GET /redoc` — ReDoc documentation

### Container Management

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/containers` | Create a new container |
| `GET` | `/containers` | List user's containers |
| `GET` | `/containers/{id}` | Get container details |
| `DELETE` | `/containers/{id}` | Stop and remove a container |
| `GET` | `/containers/{id}/health` | Get container health status |

### Configuration Management

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/config` | List all user configurations |
| `POST` | `/config` | Create a new configuration |
| `GET` | `/config/{name}` | Get a configuration (`?merged=true` for system+user merge) |
| `PUT` | `/config/{name}` | Update a configuration |
| `DELETE` | `/config/{name}` | Delete a configuration |
| `GET` | `/config/system` | Get system configuration (admin only) |
| `PUT` | `/config/system` | Update system configuration (admin only) |

### System

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Service health check (unauthenticated) |
| `GET` | `/clusters` | List compute clusters (admin only) |

## Authentication

All endpoints except `/health` require an API key via the `Authorization` header:

```
Authorization: Bearer {user_id}:{token_string}
```

Minimum total length: 20 characters.

## Compute Backends

The orchestrator supports two compute backends, selectable per-request or via the `DEFAULT_BACKEND` environment variable:

| Backend | Description |
|---------|-------------|
| `ecs` | AWS ECS Fargate — serverless tasks, managed by AWS |
| `k8s` | Kubernetes — pods on any self-managed or cloud-managed cluster |

Individual requests can override the default by including `"backend": "k8s"` or `"backend": "ecs"` in the `POST /containers` body. Once created, a container's backend is stored in DynamoDB and all subsequent operations route to the correct backend automatically.

### Kubernetes Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DEFAULT_BACKEND` | `k8s` | Compute backend when not specified per-request |
| `K8S_NAMESPACE` | `openclaw` | Namespace where pods are created |
| `K8S_IMAGE` | `openclaw-agent:latest` | Container image for agent pods |
| `K8S_IMAGE_PULL_POLICY` | `IfNotPresent` | Image pull policy |
| `K8S_IMAGE_PULL_SECRET` | _(none)_ | `imagePullSecret` for private registries |
| `K8S_KUBECONFIG` | _(none)_ | Path to a kubeconfig file |
| `K8S_KUBECONFIG_SSM_PATH` | _(none)_ | SSM Parameter Store path containing kubeconfig YAML |
| `K8S_CONTEXT` | _(current)_ | Kubernetes context to use |

**Kubeconfig loading order:** SSM Parameter Store > local file > in-cluster config > `~/.kube/config`

### ECS Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ECS_CLUSTER_NAME` | `openclaw` | ECS cluster name |
| `ECS_TASK_DEFINITION` | `openclaw-agent` | Task definition name |
| `ECS_CONTAINER_NAME` | `openclaw-agent` | Container name within the task |
| `ECS_SUBNETS` | _(none)_ | Comma-separated subnet IDs |
| `ECS_SECURITY_GROUPS` | _(none)_ | Comma-separated security group IDs |

## Configuration System

The orchestrator uses a two-tier configuration system:

```
System Config (always wins for infrastructure fields)
  ↓
User Config (user-specific fields: API keys, model preferences)
  ↓
Hardcoded Defaults (fallback)
```

### System Configuration (Admin-managed)

Infrastructure settings shared by all users:

| Parameter | Type | Description |
|-----------|------|-------------|
| `auth_gateway_url` | string | Auth gateway endpoint URL |
| `openclaw_url` | string | Agent gateway URL |
| `openclaw_token` | string | Shared service token |
| `voice_gateway_url` | string | Voice gateway WebSocket URL |

### User Configuration

Per-user settings and credentials:

| Parameter | Type | Description |
|-----------|------|-------------|
| `llm_provider` | string | `anthropic`, `openai`, or `openrouter` |
| `openclaw_model` | string | Default model name |
| `anthropic_api_key` | string | Anthropic API key |
| `openai_api_key` | string | OpenAI API key |
| `openrouter_api_key` | string | OpenRouter API key |
| `max_containers` | int | Maximum containers this user may run |

Users can maintain multiple named configurations and select one when creating a container:

```bash
# Create configs for different environments
curl -X POST .../config \
  -d '{"config_name": "production", "llm_provider": "anthropic", ...}'

curl -X POST .../config \
  -d '{"config_name": "testing", "llm_provider": "openai", ...}'

# Use a specific config when creating a container
curl -X POST .../containers \
  -d '{"config_name": "production"}'
```

### Container Environment Variables

These variables are injected into every container at creation time:

| Variable | Description |
|---|---|
| `API_KEY` | User's auth API key |
| `CONTAINER_ID` | Unique container identifier |
| `CONFIG_NAME` | Named config to load (default: `default`) |
| `ORCHESTRATOR_URL` | URL of this orchestrator service |
| `AGENT_ID` | Agent ID for registration (if supplied) |
| `OPENCLAW_DISABLE_BONJOUR` | Disables mDNS/Bonjour discovery |
| `OPENROUTER_API_KEY` | From user config (if set) |
| `ANTHROPIC_API_KEY` | From user config (if set) |
| `OPENAI_API_KEY` | From user config (if set) |

`API_KEY`, `CONTAINER_ID`, `CONFIG_NAME`, `ORCHESTRATOR_URL`, `AGENT_ID`, and `OPENCLAW_DISABLE_BONJOUR` are **protected** and cannot be overridden by caller-supplied `env_vars`.

## Tailscale (Optional)

The Lambda container can join a Tailscale tailnet on cold-start for outbound access to private services without VPN or VPC peering. Runs in userspace-networking mode — no kernel TUN module required.

| Variable | Required | Description |
|---|---|---|
| `TAILSCALE_API_KEY_SSM_PATH` | Prod | SSM path to Tailscale API key |
| `TAILSCALE_AUTH_KEY` | Dev only | Literal auth key (overrides SSM) |

If neither is set, Lambda starts normally without Tailscale.

## Architecture

```
orchestrator/
├── app/
│   ├── main.py              # FastAPI application
│   ├── config.py            # Settings (pydantic BaseSettings)
│   ├── middleware/           # Authentication middleware
│   ├── models/              # Pydantic models (container, config, cluster)
│   ├── routes/              # API endpoint handlers
│   └── services/            # Business logic (DynamoDB, ECS, Kubernetes)
├── tests/
│   ├── unit/                # Unit tests
│   ├── integration/         # Integration tests (DynamoDB Local)
│   ├── e2e/                 # End-to-end tests
│   └── post_deploy/         # Post-deployment smoke tests
├── scripts/
│   ├── manage.py            # CLI for cluster management, cleanup, reconciliation
│   └── load_defaults.py     # Load default configs into DynamoDB
├── infrastructure/          # EventBridge, Tailscale Terraform
├── docs/                    # Extended documentation
├── lambda_handler.py        # AWS Lambda entry point
├── Dockerfile.lambda        # Lambda container image (ARM64)
├── docker-compose.yml       # Local development (orchestrator + DynamoDB Local)
└── Makefile                 # Build, test, deploy targets
```

**Built with:** FastAPI, AWS Lambda (ARM64), API Gateway, DynamoDB, ECS Fargate, Kubernetes, CloudWatch, Tailscale (optional)

## Development

```bash
# Install dev dependencies
make install-dev

# Run all tests
make test

# Run unit tests only
make test-unit

# Run integration tests (requires DynamoDB Local)
make test-integration

# Run tests with coverage
make test-cov

# Full CI pipeline (lint + test + integration)
make ci

# Run E2E tests
make test-e2e           # Local with DynamoDB Local
make test-e2e-aws       # Against real AWS DynamoDB

# Lint
make lint               # black, isort, flake8
```

## Deployment

The orchestrator deploys as an ARM64 Lambda container image behind API Gateway, with DynamoDB for state and either ECS or Kubernetes for container runtime.

```bash
# Build and push Lambda image to ECR
make lambda-push ENV=dev

# Deploy infrastructure via Terraform
make deploy ENV=dev

# Tail Lambda logs
make lambda-logs ENV=dev

# Run post-deploy smoke tests
make test-deploy ENV=dev
```

See [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md) for the full deployment guide.

## Documentation

- [Getting Started](./docs/README.md) — Documentation index
- [Deployment Guide](./docs/DEPLOYMENT.md) — Deploy to AWS
- [Configuration API](./docs/CONFIG_API.md) — Config endpoint reference
- [E2E Testing](./docs/E2E_TEST_GUIDE.md) — End-to-end test guide
- [Container Requirements](./docs/CONTAINER_REQUIREMENTS.md) — Container config protocol
- [Implementation Details](./docs/IMPLEMENTATION_SUMMARY.md) — DynamoDB schema and internals

## License

MIT License. See [LICENSE](./LICENSE).
