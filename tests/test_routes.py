"""Tests for API routes."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "orchestrator"
    assert "git_sha" in data
    # git_sha can be None or a string depending on git availability
    assert data["git_sha"] is None or isinstance(data["git_sha"], str)


def test_root_endpoint(client):
    """Test root endpoint."""
    response = client.get("/")

    assert response.status_code == 200


def test_create_container_unauthorized(client):
    """Test creating a container without authentication."""
    response = client.post("/containers", json={"name": "test"})

    assert response.status_code == 401


@patch("app.middleware.auth.get_auth_client")
def test_create_container_authorized(mock_get_auth_client, authenticated_client):
    """Test creating a container with authentication."""
    # Mock auth-gateway response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"user_id": "test-user"}

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_get_auth_client.return_value = mock_client

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


@patch("app.middleware.auth.get_auth_client")
def test_list_containers_empty(mock_get_auth_client, authenticated_client):
    """Test listing containers when none exist."""
    # Mock auth-gateway response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"user_id": "test-user"}

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_get_auth_client.return_value = mock_client

    response = authenticated_client.get("/containers")

    assert response.status_code == 200
    assert response.json() == []


@patch("app.middleware.auth.get_auth_client")
def test_list_containers(mock_get_auth_client, authenticated_client, sample_container):
    """Test listing containers for a user."""
    # Mock auth-gateway response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"user_id": "test-user"}

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_get_auth_client.return_value = mock_client

    from app.services import dynamodb

    sample_container.user_id = "test-user"
    dynamodb.create_container(sample_container)

    response = authenticated_client.get("/containers")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["container_id"] == "oc-test123"


@patch("app.middleware.auth.get_auth_client")
def test_get_container_not_found(mock_get_auth_client, authenticated_client):
    """Test getting a non-existent container."""
    # Mock auth-gateway response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"user_id": "test-user"}

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_get_auth_client.return_value = mock_client

    response = authenticated_client.get("/containers/oc-nonexistent")

    assert response.status_code == 404


@patch("app.middleware.auth.get_auth_client")
def test_get_container(mock_get_auth_client, authenticated_client, sample_container):
    """Test getting a container."""
    # Mock auth-gateway response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"user_id": "test-user"}

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_get_auth_client.return_value = mock_client

    from app.services import dynamodb

    sample_container.user_id = "test-user"
    dynamodb.create_container(sample_container)

    response = authenticated_client.get("/containers/oc-test123")

    assert response.status_code == 200
    data = response.json()
    assert data["container_id"] == "oc-test123"
    assert data["status"] == "RUNNING"


@patch("app.middleware.auth.get_auth_client")
def test_delete_container(mock_get_auth_client, authenticated_client, sample_container):
    """Test deleting a container."""
    # Mock auth-gateway response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"user_id": "test-user"}

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_get_auth_client.return_value = mock_client

    from app.services import dynamodb

    sample_container.user_id = "test-user"
    dynamodb.create_container(sample_container)

    with patch("app.services.ecs._get_ecs_client") as mock_ecs:
        mock_ecs.return_value.stop_task.return_value = {}

        response = authenticated_client.delete("/containers/oc-test123")

        assert response.status_code == 204


@patch("app.middleware.auth.get_auth_client")
def test_get_container_health(mock_get_auth_client, authenticated_client, sample_container):
    """Test getting container health status."""
    # Mock auth-gateway response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"user_id": "test-user"}

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_get_auth_client.return_value = mock_client

    from app.services import dynamodb

    sample_container.user_id = "test-user"
    dynamodb.create_container(sample_container)

    response = authenticated_client.get("/containers/oc-test123/health")

    assert response.status_code == 200
    data = response.json()
    assert data["container_id"] == "oc-test123"
    assert data["health_status"] == "HEALTHY"


@patch("app.middleware.auth.get_auth_client")
def test_access_control_cross_user(mock_get_auth_client, authenticated_client, sample_container):
    """Test that users can only access their own containers."""
    # Mock auth-gateway response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"user_id": "test-user"}

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_get_auth_client.return_value = mock_client

    from app.services import dynamodb

    # Create container for different user
    sample_container.user_id = "other-user"
    dynamodb.create_container(sample_container)

    # Try to access as "test-user"
    response = authenticated_client.get("/containers/oc-test123")

    assert response.status_code == 404


def test_openapi_schema_has_bearer_auth(client):
    """Test that OpenAPI schema includes Bearer token security scheme."""
    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()

    # Check that BearerAuth security scheme is defined
    assert "components" in schema
    assert "securitySchemes" in schema["components"]
    assert "BearerAuth" in schema["components"]["securitySchemes"]

    bearer_auth = schema["components"]["securitySchemes"]["BearerAuth"]
    assert bearer_auth["type"] == "http"
    assert bearer_auth["scheme"] == "bearer"
    assert bearer_auth["bearerFormat"] == "API Key"

    # Check that security is applied to protected endpoints
    assert "/containers" in schema["paths"]
    post_method = schema["paths"]["/containers"]["post"]
    assert "security" in post_method
    assert {"BearerAuth": []} in post_method["security"]

    # Check that /health endpoint does not have security
    assert "/health" in schema["paths"]
    health_method = schema["paths"]["/health"]["get"]
    assert "security" not in health_method
