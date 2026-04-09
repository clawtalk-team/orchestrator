"""Unit tests for DynamoDB service."""

from datetime import datetime

import pytest

from app.models.container import Container, HealthData
from app.services import dynamodb


@pytest.fixture
def sample_container():
    """Create a sample container."""
    now = datetime.utcnow()
    return Container(
        container_id="oc-test123",
        user_id="user-123",
        task_arn="arn:aws:ecs:us-east-1:123456789:task/test",
        status="RUNNING",
        ip_address="10.0.1.45",
        port=8080,
        health_endpoint="http://10.0.1.45:8080/health",
        api_endpoint="http://10.0.1.45:8080",
        health_status="HEALTHY",
        health_data=HealthData(
            agents_running=2,
            uptime_seconds=360,
            memory_mb=256,
            cpu_percent=12.5,
        ),
        created_at=now,
        updated_at=now,
    )


def test_create_container(aws_mocks, sample_container):
    """Test creating a container in DynamoDB."""
    result = dynamodb.create_container(sample_container)

    assert result.container_id == "oc-test123"
    assert result.user_id == "user-123"
    assert result.status == "RUNNING"


def test_get_container(aws_mocks, sample_container):
    """Test retrieving a container from DynamoDB."""
    dynamodb.create_container(sample_container)

    result = dynamodb.get_container("user-123", "oc-test123")

    assert result is not None
    assert result.container_id == "oc-test123"
    assert result.ip_address == "10.0.1.45"
    assert result.health_status == "HEALTHY"


def test_get_container_not_found(aws_mocks):
    """Test retrieving a non-existent container."""
    result = dynamodb.get_container("user-123", "nonexistent")

    assert result is None


def test_get_user_containers(aws_mocks):
    """Test retrieving all containers for a user."""
    now = datetime.utcnow()

    container1 = Container(
        container_id="oc-test1",
        user_id="user-123",
        task_arn="arn:1",
        status="RUNNING",
        health_status="HEALTHY",
        created_at=now,
        updated_at=now,
    )

    container2 = Container(
        container_id="oc-test2",
        user_id="user-123",
        task_arn="arn:2",
        status="STOPPED",
        health_status="UNKNOWN",
        created_at=now,
        updated_at=now,
    )

    dynamodb.create_container(container1)
    dynamodb.create_container(container2)

    result = dynamodb.get_user_containers("user-123")

    assert len(result) == 2


def test_get_user_containers_filter_by_status(aws_mocks):
    """Test retrieving containers filtered by status."""
    now = datetime.utcnow()

    container1 = Container(
        container_id="oc-test1",
        user_id="user-123",
        task_arn="arn:1",
        status="RUNNING",
        health_status="HEALTHY",
        created_at=now,
        updated_at=now,
    )

    container2 = Container(
        container_id="oc-test2",
        user_id="user-123",
        task_arn="arn:2",
        status="STOPPED",
        health_status="UNKNOWN",
        created_at=now,
        updated_at=now,
    )

    dynamodb.create_container(container1)
    dynamodb.create_container(container2)

    result = dynamodb.get_user_containers("user-123", status="RUNNING")

    assert len(result) == 1
    assert result[0].status == "RUNNING"


def test_update_container(aws_mocks, sample_container):
    """Test updating a container."""
    dynamodb.create_container(sample_container)

    sample_container.status = "STOPPED"
    sample_container.health_status = "UNKNOWN"
    dynamodb.update_container(sample_container)

    result = dynamodb.get_container("user-123", "oc-test123")

    assert result.status == "STOPPED"
    assert result.health_status == "UNKNOWN"


def test_delete_container(aws_mocks, sample_container):
    """Test deleting a container."""
    dynamodb.create_container(sample_container)

    result = dynamodb.delete_container("user-123", "oc-test123")

    assert result is True

    retrieved = dynamodb.get_container("user-123", "oc-test123")
    assert retrieved is None


def test_get_user_containers_ignores_config_items(aws_mocks):
    """Test that get_user_containers filters out CONFIG items and only returns CONTAINER items."""
    now = datetime.utcnow()

    # Create a container
    container = Container(
        container_id="oc-test1",
        user_id="user-123",
        task_arn="arn:1",
        status="RUNNING",
        health_status="HEALTHY",
        created_at=now,
        updated_at=now,
    )
    dynamodb.create_container(container)

    # Manually insert a CONFIG item for the same user (simulating user config)
    table = dynamodb._get_table()
    table.put_item(
        Item={
            "pk": "USER#user-123",
            "sk": "CONFIG#default",
            "user_id": "user-123",
            "config_type": "user_config",
            "llm_provider": "anthropic",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
    )

    # Query should only return containers, not config items
    result = dynamodb.get_user_containers("user-123")

    assert len(result) == 1
    assert result[0].container_id == "oc-test1"


def test_get_running_containers(aws_mocks):
    """Test retrieving all running containers."""
    now = datetime.utcnow()

    running = Container(
        container_id="oc-running",
        user_id="user-123",
        task_arn="arn:1",
        status="RUNNING",
        health_status="HEALTHY",
        created_at=now,
        updated_at=now,
    )

    stopped = Container(
        container_id="oc-stopped",
        user_id="user-456",
        task_arn="arn:2",
        status="STOPPED",
        health_status="UNKNOWN",
        created_at=now,
        updated_at=now,
    )

    dynamodb.create_container(running)
    dynamodb.create_container(stopped)

    result = dynamodb.get_running_containers()

    assert len(result) == 1
    assert result[0].status == "RUNNING"
