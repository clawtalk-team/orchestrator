import json
import os
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

import boto3

from app.config import get_settings
from app.models.container import Container, HealthData


def _get_dynamodb():
    settings = get_settings()
    if settings.dynamodb_endpoint:
        return boto3.resource(
            "dynamodb",
            endpoint_url=settings.dynamodb_endpoint,
            region_name=settings.dynamodb_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )
    return boto3.resource("dynamodb", region_name=settings.dynamodb_region)


def _get_table():
    settings = get_settings()
    dynamodb = _get_dynamodb()
    return dynamodb.Table(settings.containers_table)


def ensure_table_exists():
    """Create containers table if it doesn't exist (for local development)."""
    settings = get_settings()
    dynamodb = _get_dynamodb()

    try:
        dynamodb.meta.client.describe_table(TableName=settings.containers_table)
    except dynamodb.meta.client.exceptions.ResourceNotFoundException:
        dynamodb.create_table(
            TableName=settings.containers_table,
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
                {"AttributeName": "user_id", "AttributeType": "S"},
                {"AttributeName": "status", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "user_id-status-index",
                    "KeySchema": [
                        {"AttributeName": "user_id", "KeyType": "HASH"},
                        {"AttributeName": "status", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
        )
        dynamodb.meta.client.get_waiter("table_exists").wait(
            TableName=settings.containers_table
        )


def _serialize_container(container: Container) -> dict:
    """Convert Container model to DynamoDB item."""
    item = {
        "pk": f"USER#{container.user_id}",
        "sk": f"CONTAINER#{container.container_id}",
        "container_id": container.container_id,
        "user_id": container.user_id,
        "task_arn": container.task_arn,
        "status": container.status,
        "port": container.port,
        "health_status": container.health_status,
        "created_at": container.created_at.isoformat(),
        "updated_at": container.updated_at.isoformat(),
    }

    if container.ip_address:
        item["ip_address"] = container.ip_address
    if container.health_endpoint:
        item["health_endpoint"] = container.health_endpoint
    if container.api_endpoint:
        item["api_endpoint"] = container.api_endpoint
    if container.last_health_check:
        item["last_health_check"] = container.last_health_check.isoformat()
    if container.health_data:
        item["health_data"] = json.dumps(
            {
                "agents_running": container.health_data.agents_running,
                "uptime_seconds": container.health_data.uptime_seconds,
                "memory_mb": container.health_data.memory_mb,
                "cpu_percent": container.health_data.cpu_percent,
                "version": container.health_data.version,
                "agents": container.health_data.agents,
            }
        )

    return item


def _deserialize_container(item: dict) -> Container:
    """Convert DynamoDB item to Container model."""
    health_data = None
    if "health_data" in item and item["health_data"]:
        try:
            data = json.loads(item["health_data"])
            health_data = HealthData(**data)
        except (json.JSONDecodeError, ValueError):
            pass

    # Parse last_health_check safely
    last_health_check = None
    if "last_health_check" in item and item["last_health_check"]:
        try:
            last_health_check = datetime.fromisoformat(item["last_health_check"])
        except (ValueError, TypeError):
            pass

    return Container(
        container_id=item["container_id"],
        user_id=item["user_id"],
        task_arn=item["task_arn"],
        status=item["status"],
        ip_address=item.get("ip_address"),
        port=item.get("port", 8080),
        health_endpoint=item.get("health_endpoint"),
        api_endpoint=item.get("api_endpoint"),
        health_status=item.get("health_status", "UNKNOWN"),
        last_health_check=last_health_check,
        health_data=health_data,
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
    )


def create_container(container: Container) -> Container:
    """Create a new container record."""
    table = _get_table()
    item = _serialize_container(container)
    table.put_item(Item=item)
    return container


def get_container(user_id: str, container_id: str) -> Optional[Container]:
    """Get a container by user_id and container_id."""
    table = _get_table()
    response = table.get_item(
        Key={
            "pk": f"USER#{user_id}",
            "sk": f"CONTAINER#{container_id}",
        }
    )

    if "Item" not in response:
        return None

    return _deserialize_container(response["Item"])


def get_user_containers(user_id: str, status: Optional[str] = None) -> List[Container]:
    """Get all containers for a user, optionally filtered by status."""
    table = _get_table()

    if status:
        response = table.query(
            IndexName="user_id-status-index",
            KeyConditionExpression="user_id = :user_id AND #s = :status",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":user_id": user_id,
                ":status": status,
            },
        )
    else:
        response = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :sk_prefix)",
            ExpressionAttributeValues={
                ":pk": f"USER#{user_id}",
                ":sk_prefix": "CONTAINER#",
            },
        )

    return [_deserialize_container(item) for item in response.get("Items", [])]


def update_container(container: Container) -> Container:
    """Update an existing container record."""
    table = _get_table()
    item = _serialize_container(container)
    table.put_item(Item=item)
    return container


def delete_container(user_id: str, container_id: str) -> bool:
    """Delete a container record."""
    table = _get_table()
    table.delete_item(
        Key={
            "pk": f"USER#{user_id}",
            "sk": f"CONTAINER#{container_id}",
        }
    )
    return True


def get_running_containers() -> List[Container]:
    """
    Get all running containers (for health checks).

    Note: This scans the GSI which is more efficient than scanning the main table,
    but a dedicated GSI with status as partition key would be optimal for large scale.
    """
    table = _get_table()
    # Scan the GSI instead of the main table for better performance
    response = table.scan(
        IndexName="user_id-status-index",
        FilterExpression="#s = :status",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":status": "RUNNING"},
    )

    return [_deserialize_container(item) for item in response.get("Items", [])]
