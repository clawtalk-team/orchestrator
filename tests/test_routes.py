"""Tests for API routes."""

import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock
from app.models.container import Container


@pytest.fixture
def sample_container():
    """Create a sample container."""
    now = datetime.utcnow()
    return Container(
        container_id="oc-test123",
        user_id="test-user",
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


def test_health_endpoint(client):
    """Test health check endpoint."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_root_endpoint(client):
    """Test root endpoint."""
    response = client.get("/")

    assert response.status_code == 200


def test_create_container_unauthorized(client):
    """Test creating a container without authentication."""
    response = client.post("/containers", json={"name": "test"})

    assert response.status_code == 401


def test_create_container_authorized(authenticated_client):
    """Test creating a container with authentication."""
    with patch("app.services.ecs._get_ecs_client") as mock_ecs:
        mock_ecs.return_value.run_task.return_value = {
            "tasks": [
                {
                    "taskArn": "arn:aws:ecs:us-east-1:123456789:task/test",
                    "attachments": [
                        {
                            "type": "ElasticNetworkInterface",
                            "details": [
                                {
                                    "name": "privateIPv4Address",
                                    "value": "10.0.1.45",
                                }
                            ],
                        }
                    ],
                }
            ]
        }

        response = authenticated_client.post(
            "/containers",
            json={"name": "test-container"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "container_id" in data
        assert data["status"] == "PENDING"


def test_list_containers_empty(authenticated_client):
    """Test listing containers when none exist."""
    response = authenticated_client.get("/containers")

    assert response.status_code == 200
    assert response.json() == []


def test_list_containers(authenticated_client, sample_container):
    """Test listing containers for a user."""
    from app.services import dynamodb

    sample_container.user_id = "test-user"
    dynamodb.create_container(sample_container)

    response = authenticated_client.get("/containers")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["container_id"] == "oc-test123"


def test_get_container_not_found(authenticated_client):
    """Test getting a non-existent container."""
    response = authenticated_client.get("/containers/oc-nonexistent")

    assert response.status_code == 404


def test_get_container(authenticated_client, sample_container):
    """Test getting a container."""
    from app.services import dynamodb

    sample_container.user_id = "test-user"
    dynamodb.create_container(sample_container)

    response = authenticated_client.get("/containers/oc-test123")

    assert response.status_code == 200
    data = response.json()
    assert data["container_id"] == "oc-test123"
    assert data["status"] == "RUNNING"


def test_delete_container(authenticated_client, sample_container):
    """Test deleting a container."""
    from app.services import dynamodb

    sample_container.user_id = "test-user"
    dynamodb.create_container(sample_container)

    with patch("app.services.ecs._get_ecs_client") as mock_ecs:
        mock_ecs.return_value.stop_task.return_value = {}

        response = authenticated_client.delete("/containers/oc-test123")

        assert response.status_code == 204


def test_get_container_health(authenticated_client, sample_container):
    """Test getting container health status."""
    from app.services import dynamodb

    sample_container.user_id = "test-user"
    dynamodb.create_container(sample_container)

    response = authenticated_client.get("/containers/oc-test123/health")

    assert response.status_code == 200
    data = response.json()
    assert data["container_id"] == "oc-test123"
    assert data["health_status"] == "HEALTHY"


def test_access_control_cross_user(authenticated_client, sample_container):
    """Test that users can only access their own containers."""
    from app.services import dynamodb

    # Create container for different user
    sample_container.user_id = "other-user"
    dynamodb.create_container(sample_container)

    # Try to access as "test-user"
    response = authenticated_client.get("/containers/oc-test123")

    assert response.status_code == 404
