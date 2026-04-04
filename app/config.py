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
        ssm = boto3.client("ssm", region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
        response = ssm.get_parameter(Name=path, WithDecryption=True)
        config = json.loads(response["Parameter"]["Value"])
        for key, value in config.items():
            if key not in os.environ:  # don't override explicit env vars
                os.environ[key] = str(value)
    except Exception as e:
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
    dynamodb_region: str = Field(default="us-east-1", alias="AWS_DEFAULT_REGION")
    aws_access_key_id: str = "local"
    aws_secret_access_key: str = "local"
    containers_table: str = "openclaw-containers"

    # ECS
    ecs_cluster_name: str = "openclaw"
    ecs_task_definition: str = "openclaw-agent"
    ecs_container_name: str = "openclaw-agent"

    # Auth Gateway
    auth_gateway_url: str = "http://localhost:8001"

    # SSM Parameter Store
    ssm_prefix: str = "/clawtalk/orchestrator"


@lru_cache
def get_settings() -> Settings:
    return Settings()
