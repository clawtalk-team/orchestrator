"""Unit tests for models."""

from datetime import datetime

import pytest

from app.models.container import Container, ContainerRequest, HealthData


def test_container_model():
    """Test Container model creation and serialization."""
    now = datetime.utcnow()

    container = Container(
        container_id="oc-test123",
        user_id="user-123",
        task_arn="arn:aws:ecs:us-east-1:123456789:task/test",
        status="RUNNING",
        ip_address="10.0.1.45",
        port=8080,
        health_endpoint="http://10.0.1.45:8080/health",
        api_endpoint="http://10.0.1.45:8080",
        health_status="HEALTHY",
        created_at=now,
        updated_at=now,
    )

    assert container.container_id == "oc-test123"
    assert container.user_id == "user-123"
    assert container.status == "RUNNING"
    assert container.health_status == "HEALTHY"


def test_container_request_model():
    """Test ContainerRequest model."""
    req = ContainerRequest(
        name="test-container",
        config_name="default",
    )

    assert req.name == "test-container"
    assert req.config_name == "default"


def test_health_data_model():
    """Test HealthData model."""
    health = HealthData(
        agents_running=2,
        uptime_seconds=360,
        memory_mb=256,
        cpu_percent=12.5,
        version="0.1.0",
        agents=[
            {
                "agent_id": "agent-1",
                "name": "Test Agent",
                "status": "connected",
            }
        ],
    )

    assert health.agents_running == 2
    assert health.uptime_seconds == 360
    assert len(health.agents) == 1
    assert health.agents[0]["agent_id"] == "agent-1"
