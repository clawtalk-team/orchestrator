import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import boto3
import httpx

from app.config import get_settings
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


def _update_agent_container(user_id: str, agent_id: str, container_id: str, api_key: str) -> None:
    """Notify auth-gateway of the container assigned to an agent."""
    settings = get_settings()
    url = f"{settings.auth_gateway_url}/users/{user_id}/agents/{agent_id}"
    try:
        response = httpx.put(
            url,
            json={"container_id": container_id},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=settings.auth_gateway_timeout,
        )
        if response.status_code == 200:
            logger.info(
                "agent container updated: agent=%s container=%s",
                agent_id,
                container_id,
            )
        else:
            logger.warning(
                "agent container update failed: agent=%s container=%s status=%s body=%s",
                agent_id,
                container_id,
                response.status_code,
                response.text,
            )
    except httpx.RequestError as e:
        logger.error(
            "agent container update error: agent=%s container=%s error=%s",
            agent_id,
            container_id,
            e,
        )


def create_container(
    user_id: str,
    api_key: str,
    config_name: str = "default",
    agent_id: Optional[str] = None,
    env_vars: Optional[Dict[str, str]] = None,
) -> Container:
    """
    Create a new ECS container for a user.

    The container will fetch its configuration from DynamoDB on startup.
    If user config does not exist, it will be created with defaults.

    Args:
        user_id: The user ID
        api_key: The API key for auth-gateway (from Authorization header)
        config_name: Named configuration to use (default: "default")
        agent_id: Optional agent ID to run in the container
        env_vars: Additional environment variables to pass to the container

    Returns:
        Container record in PENDING status.
        The actual ECS task creation is async and will be updated when RUNNING.
    """
    settings = get_settings()
    container_id = _generate_container_id()
    now = datetime.now(timezone.utc)

    logger.info("create_container start: container=%s user=%s config=%s", container_id, user_id, config_name)

    # 1. Ensure user config exists with defaults and current API key
    config_service = UserConfigService()
    config_service.ensure_container_defaults(user_id=user_id, config_name=config_name, api_key=api_key)
    logger.info("create_container config saved: container=%s config=%s", container_id, config_name)

    # 3. Create Container record in PENDING status
    container = Container(
        container_id=container_id,
        user_id=user_id,
        task_arn="",  # Will be updated when task starts
        status="PENDING",
        agent_id=agent_id,
        health_status="UNKNOWN",
        created_at=now,
        updated_at=now,
    )

    # Save to DynamoDB
    dynamodb.create_container(container)
    logger.info("create_container db record created: container=%s status=PENDING", container_id)

    # 4. Start ECS task asynchronously
    try:
        ecs = _get_ecs_client()

        # Environment variables - container fetches config from orchestrator API
        environment = [
            {"name": "API_KEY", "value": api_key},
            {"name": "CONTAINER_ID", "value": container_id},
            {"name": "CONFIG_NAME", "value": config_name},
            {"name": "ORCHESTRATOR_URL", "value": settings.orchestrator_url},
            {"name": "OPENCLAW_DISABLE_BONJOUR", "value": "1"},
        ]

        if agent_id:
            environment.append({"name": "AGENT_ID", "value": agent_id})

        # Add user-provided environment variables, deduplicating by key
        # Protected keys cannot be overridden by user-supplied env vars
        if env_vars:
            protected_keys = {"API_KEY", "CONTAINER_ID", "CONFIG_NAME", "ORCHESTRATOR_URL", "AGENT_ID", "OPENCLAW_DISABLE_BONJOUR"}
            filtered_vars = {k: v for k, v in env_vars.items() if k not in protected_keys}
            env_dict = {e["name"]: e["value"] for e in environment}
            env_dict.update(filtered_vars)
            environment = [{"name": k, "value": v} for k, v in env_dict.items()]
            if filtered_vars:
                logger.info("Added %d custom env vars to container %s", len(filtered_vars), container_id)

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

        logger.info(
            "create_container launching ECS task: container=%s cluster=%s task_def=%s",
            container_id,
            settings.ecs_cluster_name,
            settings.ecs_task_definition,
        )
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

        failures = response.get("failures", [])
        if failures:
            logger.error(
                "create_container ECS failures: container=%s failures=%s",
                container_id,
                failures,
            )

        if response.get("tasks"):
            task_arn = response["tasks"][0]["taskArn"]
            container.task_arn = task_arn
            container.updated_at = datetime.now(timezone.utc)
            dynamodb.update_container(container)
            logger.info(
                "create_container ECS task launched: container=%s task_arn=%s",
                container_id,
                task_arn,
            )

            if agent_id:
                _update_agent_container(
                    user_id=user_id,
                    agent_id=agent_id,
                    container_id=container_id,
                    api_key=api_key,
                )
        else:
            logger.error(
                "create_container ECS returned no tasks: container=%s response=%s",
                container_id,
                response,
            )
            container.status = "FAILED"
            container.updated_at = datetime.now(timezone.utc)
            dynamodb.update_container(container)
    except Exception as e:
        # If task creation fails, mark container as FAILED
        logger.exception("create_container ECS error: container=%s error=%s", container_id, e)
        container.status = "FAILED"
        container.updated_at = datetime.now(timezone.utc)
        dynamodb.update_container(container)
        raise

    logger.info("create_container complete: container=%s task_arn=%s", container_id, container.task_arn)
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
            logger.info("handle_task_event IP extracted: container=%s ip=%s", container_id, endpoints["ip_address"])
        else:
            logger.warning(
                "handle_task_event no IP in RUNNING event: container=%s task=%s — "
                "container will have no ip_address in DynamoDB",
                container_id,
                task_arn,
            )

        container.status = "RUNNING"
        container.health_status = "STARTING"
        container.updated_at = datetime.now(timezone.utc)
        dynamodb.update_container(container)
        logger.info("handle_task_event container RUNNING: container=%s ip=%s", container_id, container.ip_address)

    elif status in ("STOPPED", "STOPPING", "DEPROVISIONING"):
        stop_code = detail.get("stopCode")
        stop_reason = detail.get("stoppedReason")
        logger.info(
            "handle_task_event container stopped: container=%s status=%s code=%s reason=%s",
            container_id,
            status,
            stop_code,
            stop_reason,
        )
        container.status = "STOPPED"
        container.updated_at = datetime.now(timezone.utc)
        dynamodb.update_container(container)
        logger.info("handle_task_event db updated STOPPED: container=%s", container_id)
