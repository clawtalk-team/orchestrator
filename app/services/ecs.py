import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import boto3

from app.config import get_settings
from app.constants import DEFAULT_LLM_PROVIDER, DEFAULT_OPENCLAW_MODEL
from app.models.container import Container
from app.services import dynamodb
from app.services.user_config import UserConfigService

logger = logging.getLogger(__name__)


def _get_ecs_client():
    settings = get_settings()
    return boto3.client("ecs", region_name=settings.dynamodb_region)


def _generate_container_id() -> str:
    """Generate a container ID."""
    return f"oc-{uuid.uuid4().hex[:8]}"


def _get_orchestrator_url() -> str:
    """Get the orchestrator URL that containers should use to fetch config."""
    # Check for explicit config first
    orchestrator_url = os.getenv("ORCHESTRATOR_URL")
    if orchestrator_url:
        return orchestrator_url

    # For Lambda/AWS deployments, containers should use the API Gateway URL
    # This should be configured in SSM or environment
    # Default to localhost for local development
    return "http://localhost:8000"


def create_container(
    user_id: str,
    api_key: str,
    config_name: str = "default",
) -> Container:
    """
    Create a new ECS container for a user.

    The container will fetch its configuration from DynamoDB on startup.
    If user config does not exist, it will be created with defaults.

    Args:
        user_id: The user ID
        api_key: The API key for auth-gateway (from Authorization header)
        config_name: Named configuration to use (default: "default")

    Returns:
        Container record in PENDING status.
        The actual ECS task creation is async and will be updated when RUNNING.
    """
    settings = get_settings()
    container_id = _generate_container_id()
    now = datetime.now(timezone.utc)

    # 1. Get or create user config with defaults
    config_service = UserConfigService()
    user_config = config_service.get_user_config(user_id, config_name) or {}

    # Set defaults if not present
    if "llm_provider" not in user_config:
        user_config["llm_provider"] = DEFAULT_LLM_PROVIDER
    if "openclaw_model" not in user_config:
        user_config["openclaw_model"] = DEFAULT_OPENCLAW_MODEL

    # 2. Store api_key in user config (plaintext for now)
    user_config["auth_gateway_api_key"] = api_key

    config_service.save_user_config(
        user_id=user_id,
        config_name=config_name,
        config=user_config,
        overwrite=False,  # Merge with existing
    )

    # 3. Create Container record in PENDING status
    container = Container(
        container_id=container_id,
        user_id=user_id,
        task_arn="",  # Will be updated when task starts
        status="PENDING",
        health_status="UNKNOWN",
        created_at=now,
        updated_at=now,
    )

    # Save to DynamoDB
    dynamodb.create_container(container)

    # 4. Start ECS task asynchronously
    try:
        ecs = _get_ecs_client()

        # Get user's API key for config API authentication
        config_service = UserConfigService()
        user_config = config_service.get_user_config(user_id, config_name)
        if not user_config or not user_config.get("auth_gateway_api_key"):
            raise ValueError(f"User config missing auth_gateway_api_key for config: {config_name}")

        api_key = user_config["auth_gateway_api_key"]

        # Environment variables - container fetches config from orchestrator API
        environment = [
            {"name": "API_KEY", "value": api_key},
            {"name": "CONTAINER_ID", "value": container_id},
            {"name": "CONFIG_NAME", "value": config_name},
            {"name": "ORCHESTRATOR_URL", "value": _get_orchestrator_url()},
            {"name": "OPENCLAW_DISABLE_BONJOUR", "value": "1"},
        ]

        overrides = {
            "containerOverrides": [
                {"name": settings.ecs_container_name, "environment": environment}
            ]
        }

        # Get VPC configuration from environment
        subnets = [s.strip() for s in settings.ecs_subnets.split(",") if s.strip()]
        security_groups = [
            sg.strip() for sg in settings.ecs_security_groups.split(",") if sg.strip()
        ]

        response = ecs.run_task(
            cluster=settings.ecs_cluster_name,
            taskDefinition=settings.ecs_task_definition,
            launchType="FARGATE",
            networkConfiguration={
                "awsvpcConfiguration": {
                    "subnets": subnets,
                    "securityGroups": security_groups,
                    "assignPublicIp": "DISABLED",
                }
            },
            overrides=overrides,
            tags=[
                {"key": "user_id", "value": user_id},
                {"key": "container_id", "value": container_id},
            ],
        )

        if response.get("tasks"):
            task_arn = response["tasks"][0]["taskArn"]
            container.task_arn = task_arn
            container.updated_at = datetime.now(timezone.utc)
            dynamodb.update_container(container)
    except Exception as e:
        # If task creation fails, mark container as FAILED
        container.status = "FAILED"
        container.updated_at = datetime.now(timezone.utc)
        dynamodb.update_container(container)
        raise

    return container


def stop_container(user_id: str, container_id: str) -> bool:
    """Stop a running ECS container."""
    container = dynamodb.get_container(user_id, container_id)
    if not container:
        return False

    if not container.task_arn:
        return True  # Already stopped or never started

    try:
        ecs = _get_ecs_client()
        settings = get_settings()
        ecs.stop_task(
            cluster=settings.ecs_cluster_name,
            task=container.task_arn,
            reason="Stopped by orchestrator",
        )

        # Update status to STOPPED
        container.status = "STOPPED"
        container.updated_at = datetime.now(timezone.utc)
        dynamodb.update_container(container)
        return True
    except Exception as e:
        return False


def get_container_details(user_id: str, container_id: str) -> Optional[Container]:
    """Get container details from DynamoDB."""
    return dynamodb.get_container(user_id, container_id)


def extract_container_endpoint(task: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """
    Extract IP address from ECS task attachments.

    Called when task reaches RUNNING state to populate health_endpoint.
    """
    if "attachments" not in task:
        return None

    for attachment in task.get("attachments", []):
        if attachment.get("type") != "ElasticNetworkInterface":
            continue

        for detail in attachment.get("details", []):
            if detail.get("name") == "privateIPv4Address":
                ip_address = detail.get("value")
                return {
                    "ip_address": ip_address,
                    "port": 8080,
                    "health_endpoint": f"http://{ip_address}:8080/health",
                    "api_endpoint": f"http://{ip_address}:8080",
                }

    return None


def handle_task_event(event: Dict[str, Any]) -> None:
    """
    Handle ECS task state change events from EventBridge.

    Updates container records when task reaches RUNNING or stops.
    """
    logger.info(f"Received ECS task event: source={event.get('source')}, detail-type={event.get('detail-type')}")

    detail = event.get("detail", {})
    task_arn = detail.get("taskArn")
    status = detail.get("lastStatus")

    logger.info(f"Task ARN: {task_arn}, Status: {status}")

    if not task_arn:
        logger.warning("No task ARN in event, skipping")
        return

    # Extract user_id and container_id from tags
    # EventBridge events don't include tags by default, so fetch from ECS API
    tags = detail.get("tags", [])

    if not tags:
        # Fetch tags from ECS API
        logger.info("Tags not in event, fetching from ECS API")
        try:
            settings = get_settings()
            ecs = _get_ecs_client()
            cluster_name = settings.ecs_cluster_name
            task_id = task_arn.split("/")[-1]  # Extract task ID from ARN

            response = ecs.describe_tasks(
                cluster=cluster_name,
                tasks=[task_id],
                include=["TAGS"]
            )

            if response.get("tasks"):
                tags = response["tasks"][0].get("tags", [])
                logger.info(f"Fetched tags from ECS API: {tags}")
        except Exception as e:
            logger.error(f"Failed to fetch tags from ECS API: {e}")
            return
    else:
        logger.info(f"Task tags from event: {tags}")

    user_id = None
    container_id = None

    for tag in tags:
        if tag.get("key") == "user_id":
            user_id = tag.get("value")
        elif tag.get("key") == "container_id":
            container_id = tag.get("value")

    logger.info(f"Extracted user_id={user_id}, container_id={container_id}")

    if not user_id or not container_id:
        logger.warning(f"Missing user_id or container_id in tags, skipping")
        return

    container = dynamodb.get_container(user_id, container_id)
    if not container:
        logger.warning(f"Container not found: user_id={user_id}, container_id={container_id}")
        return

    logger.info(f"Found container, current status: {container.status}")

    if status == "RUNNING":
        # Extract IP and populate health endpoint
        endpoints = extract_container_endpoint(detail)
        if endpoints:
            container.ip_address = endpoints["ip_address"]
            container.health_endpoint = endpoints["health_endpoint"]
            container.api_endpoint = endpoints["api_endpoint"]
            logger.info(f"Extracted endpoints: {endpoints}")

        container.status = "RUNNING"
        container.health_status = "STARTING"
        container.updated_at = datetime.now(timezone.utc)
        dynamodb.update_container(container)
        logger.info(f"Updated container to RUNNING: {container_id}")

    elif status in ("STOPPED", "STOPPING", "DEPROVISIONING"):
        container.status = "STOPPED"
        container.updated_at = datetime.now(timezone.utc)
        dynamodb.update_container(container)
        logger.info(f"Updated container to STOPPED: {container_id}")
