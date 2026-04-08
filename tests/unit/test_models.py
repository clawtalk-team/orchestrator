"""Unit tests for container models."""
from datetime import datetime, timezone

import pytest

from app.models.container import Container, ContainerRequest, ContainerResponse, HealthData


def test_container_model():
    """Test Container model instantiation."""
    now = datetime.utcnow()
    container = Container(
        container_id="oc-test123",
        user_id="user-456",
        task_arn="arn:aws:ecs:region:account:task/cluster/task-id",
        status="RUNNING",
        ip_address="10.0.1.45",
        port=8080,
        health_status="HEALTHY",
        created_at=now,
        updated_at=now,
    )

    assert container.container_id == "oc-test123"
    assert container.user_id == "user-456"
    assert container.status == "RUNNING"
    assert container.health_status == "HEALTHY"
    assert container.ip_address == "10.0.1.45"
    assert container.port == 8080


def test_health_data_model():
    """Test HealthData model."""
    health = HealthData(
        agents_running=2,
        uptime_seconds=360,
        memory_mb=256,
        cpu_percent=12.5,
        version="0.1.0",
        agents=[{"agent_id": "agent-1", "name": "Test Agent"}],
    )

    assert health.agents_running == 2
    assert health.uptime_seconds == 360
    assert health.memory_mb == 256
    assert health.version == "0.1.0"
    assert len(health.agents) == 1


def test_container_request_model():
    """Test ContainerRequest model."""
    request = ContainerRequest(name="test-container", config_name="default")

    assert request.name == "test-container"
    assert request.config_name == "default"


def test_container_response_model():
    """Test ContainerResponse model includes task_arn."""
    now = datetime.now(timezone.utc)
    response = ContainerResponse(
        container_id="oc-test123",
        task_arn="arn:aws:ecs:region:account:task/cluster/task-id",
        status="RUNNING",
        ip_address="10.0.1.45",
        health_status="HEALTHY",
        created_at=now,
        updated_at=now,
    )

    assert response.container_id == "oc-test123"
    assert response.task_arn == "arn:aws:ecs:region:account:task/cluster/task-id"
    assert response.status == "RUNNING"
    assert response.health_status == "HEALTHY"
    assert response.ip_address == "10.0.1.45"


def test_container_response_model_with_none_task_arn():
    """Test ContainerResponse model with None task_arn."""
    now = datetime.now(timezone.utc)
    response = ContainerResponse(
        container_id="oc-test123",
        task_arn=None,
        status="PENDING",
        health_status="UNKNOWN",
        created_at=now,
        updated_at=now,
    )

    assert response.container_id == "oc-test123"
    assert response.task_arn is None
    assert response.status == "PENDING"
    assert response.health_status == "UNKNOWN"
