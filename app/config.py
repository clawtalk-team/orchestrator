import json
import os
from functools import lru_cache
from typing import Optional

from pydantic import ConfigDict, Field
from pydantic_settings import BaseSettings


def _load_ssm_config() -> None:
    """If SSM_CONFIG_PATH is set, fetch the JSON SecureString and populate os.environ."""
    path = os.environ.get("SSM_CONFIG_PATH")
    if not path:
        return
    try:
        import boto3
        from botocore.exceptions import ClientError

        # Lambda sets AWS_REGION automatically, fall back to DYNAMODB_REGION or default
        region = os.environ.get("AWS_REGION") or os.environ.get(
            "DYNAMODB_REGION", "us-east-1"
        )
        ssm = boto3.client("ssm", region_name=region)
        response = ssm.get_parameter(Name=path, WithDecryption=True)
        config = json.loads(response["Parameter"]["Value"])
        for key, value in config.items():
            if key not in os.environ:  # don't override explicit env vars
                os.environ[key] = str(value)
    except (ClientError, json.JSONDecodeError, KeyError) as e:
        print(f"Warning: could not load SSM config from {path}: {e}")


_load_ssm_config()


class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", extra="ignore")

    app_name: str = "orchestrator"
    debug: bool = False

    # Master API key for system-to-system access
    master_api_key: str = ""

    # DynamoDB
    dynamodb_endpoint: Optional[str] = None
    dynamodb_region: str = (
        "us-east-1"  # Lambda sets AWS_REGION, can also use DYNAMODB_REGION
    )
    aws_access_key_id: str = "local"
    aws_secret_access_key: str = "local"
    containers_table: str = "openclaw-containers"

    # ECS
    ecs_cluster_name: str = "openclaw"
    ecs_task_definition: str = "openclaw-agent"
    ecs_container_name: str = "openclaw-agent"
    ecs_subnets: str = ""  # Comma-separated subnet IDs
    ecs_security_groups: str = ""  # Comma-separated security group IDs

    # Auth Gateway
    # Must be set via AUTH_GATEWAY_URL env var in production.
    # Defaults to localhost only for local development.
    auth_gateway_url: str = "http://localhost:8001"
    auth_gateway_timeout: float = 5.0  # seconds

    # OpenClaw / Voice Gateway
    openclaw_url: str = "http://localhost:18789"
    voice_gateway_url: str = "ws://localhost:9090"
    # openclaw_gateway_token is intentionally excluded — it's a secret and has no
    # safe local default. Set OPENCLAW_GATEWAY_TOKEN env var or DynamoDB system config.

    # Orchestrator API URL (for containers to fetch config)
    orchestrator_url: str = "http://localhost:8000"

    # SSM Parameter Store
    ssm_prefix: str = "/clawtalk/orchestrator"

    # Kubernetes
    k8s_namespace: str = "openclaw"
    k8s_image: str = "openclaw-agent:latest"
    k8s_image_pull_policy: str = "IfNotPresent"  # Never | IfNotPresent | Always
    k8s_kubeconfig: Optional[str] = None  # Path to kubeconfig; None = default/in-cluster
    k8s_context: Optional[str] = None  # Kubernetes context to use; None = current context
    default_backend: str = "ecs"  # Compute backend: "ecs" or "k8s"


@lru_cache
def get_settings() -> Settings:
    return Settings()
