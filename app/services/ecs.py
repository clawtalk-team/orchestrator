import boto3
import os
import uuid
from datetime import datetime
from typing import Optional, Dict, Any
import json

from app.config import get_settings
from app.models.container import Container
from app.services import dynamodb
from app.services.config_store import store_config


def _get_ecs_client():
    settings = get_settings()
    return boto3.client("ecs", region_name=settings.dynamodb_region)


def _generate_container_id() -> str:
    """Generate a container ID."""
    return f"oc-{uuid.uuid4().hex[:8]}"


def create_container(user_id: str, config: Optional[Dict[str, Any]] = None) -> Container:
    """
    Create a new ECS container for a user.

    Returns a Container record in PENDING status.
    The actual ECS task creation is async and will be updated when RUNNING.
    """
    settings = get_settings()
    container_id = _generate_container_id()
    now = datetime.utcnow()

    # Store config in SSM if provided
    config_param_name = None
    if config:
        config_param_name = store_config(user_id, container_id, config)

    # Create Container record in PENDING status
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

    # Start ECS task asynchronously
    try:
        ecs = _get_ecs_client()
        overrides = {
            "containerOverrides": [
                {
                    "name": settings.ecs_container_name,
                    "environment": [
                        {
                            "name": "CONTAINER_ID",
                            "value": container_id,
                        },
                        {
                            "name": "USER_ID",
                            "value": user_id,
                        },
                    ],
                }
            ]
        }

        if config_param_name:
            overrides["containerOverrides"][0]["environment"].append({
                "name": "SSM_CONFIG_PATH",
                "value": config_param_name,
            })

        # Get VPC configuration from environment
        subnets = [s.strip() for s in settings.ecs_subnets.split(",") if s.strip()]
        security_groups = [sg.strip() for sg in settings.ecs_security_groups.split(",") if sg.strip()]

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
            container.updated_at = datetime.utcnow()
            dynamodb.update_container(container)
    except Exception as e:
        # If task creation fails, mark container as FAILED
        container.status = "FAILED"
        container.updated_at = datetime.utcnow()
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
        container.updated_at = datetime.utcnow()
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
    detail = event.get("detail", {})
    task_arn = detail.get("taskArn")
    status = detail.get("lastStatus")

    if not task_arn:
        return

    # Extract user_id and container_id from tags
    tags = detail.get("tags", [])
    user_id = None
    container_id = None

    for tag in tags:
        if tag.get("key") == "user_id":
            user_id = tag.get("value")
        elif tag.get("key") == "container_id":
            container_id = tag.get("value")

    if not user_id or not container_id:
        return

    container = dynamodb.get_container(user_id, container_id)
    if not container:
        return

    if status == "RUNNING":
        # Extract IP and populate health endpoint
        endpoints = extract_container_endpoint(detail)
        if endpoints:
            container.ip_address = endpoints["ip_address"]
            container.health_endpoint = endpoints["health_endpoint"]
            container.api_endpoint = endpoints["api_endpoint"]

        container.status = "RUNNING"
        container.health_status = "STARTING"
        container.updated_at = datetime.utcnow()
        dynamodb.update_container(container)

    elif status in ("STOPPED", "STOPPING", "DEPROVISIONING"):
        container.status = "STOPPED"
        container.updated_at = datetime.utcnow()
        dynamodb.update_container(container)
