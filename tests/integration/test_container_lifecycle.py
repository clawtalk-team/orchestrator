"""Integration tests for container lifecycle."""
import os
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services import dynamodb

# Skip if not running integration tests
pytestmark = pytest.mark.skipif(
    not os.environ.get("INTEGRATION_TESTS"),
    reason="Integration tests disabled (set INTEGRATION_TESTS=1)",
)


@pytest.fixture(scope="module", autouse=True)
def setup_dynamodb():
    """Ensure DynamoDB table exists for integration tests."""
    settings = get_settings()
    if settings.dynamodb_endpoint:
        dynamodb.ensure_table_exists()
    yield
    # Cleanup after tests
    # Note: In production, we don't delete the table


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def auth_headers():
    """Create auth headers with test user."""
    return {"Authorization": "Bearer test-user-123:test-token-abc123"}


def test_health_endpoint(client):
    """Test health endpoint is accessible."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_create_container(client, auth_headers):
    """Test container creation."""
    response = client.post(
        "/containers",
        json={"name": "test-container", "config": {"test": "value"}},
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert "container_id" in data
    assert data["status"] in ["PENDING", "RUNNING"]

    # Verify container is in DynamoDB
    container = dynamodb.get_container("test-user-123", data["container_id"])
    assert container is not None
    assert container.user_id == "test-user-123"


def test_list_containers(client, auth_headers):
    """Test listing containers."""
    # First create a container
    create_response = client.post(
        "/containers", json={"name": "test-list", "config": {}}, headers=auth_headers
    )
    assert create_response.status_code == 200

    # Now list containers
    response = client.get("/containers", headers=auth_headers)
    assert response.status_code == 200

    containers = response.json()
    assert isinstance(containers, list)
    assert len(containers) >= 1

    # Verify our container is in the list
    container_ids = [c["container_id"] for c in containers]
    assert create_response.json()["container_id"] in container_ids


def test_get_container(client, auth_headers):
    """Test getting specific container details."""
    # Create a container
    create_response = client.post(
        "/containers", json={"name": "test-get", "config": {}}, headers=auth_headers
    )
    container_id = create_response.json()["container_id"]

    # Get container details
    response = client.get(f"/containers/{container_id}", headers=auth_headers)
    assert response.status_code == 200

    data = response.json()
    assert data["container_id"] == container_id


def test_get_container_not_found(client, auth_headers):
    """Test getting non-existent container."""
    response = client.get("/containers/nonexistent-id", headers=auth_headers)
    assert response.status_code == 404


def test_delete_container(client, auth_headers):
    """Test deleting a container."""
    # Create a container
    create_response = client.post(
        "/containers", json={"name": "test-delete", "config": {}}, headers=auth_headers
    )
    container_id = create_response.json()["container_id"]

    # Delete it
    response = client.delete(f"/containers/{container_id}", headers=auth_headers)
    assert response.status_code == 204


def test_get_container_health(client, auth_headers):
    """Test getting container health status."""
    # Create a container
    create_response = client.post(
        "/containers", json={"name": "test-health", "config": {}}, headers=auth_headers
    )
    container_id = create_response.json()["container_id"]

    # Get health
    response = client.get(f"/containers/{container_id}/health", headers=auth_headers)
    assert response.status_code == 200

    data = response.json()
    assert data["container_id"] == container_id
    assert "health_status" in data


def test_user_isolation(client):
    """Test that users can only see their own containers."""
    # Create container for user1
    user1_headers = {"Authorization": "Bearer user1:token1"}
    create_response = client.post(
        "/containers",
        json={"name": "user1-container", "config": {}},
        headers=user1_headers,
    )
    container_id = create_response.json()["container_id"]

    # Try to access with user2
    user2_headers = {"Authorization": "Bearer user2:token2"}
    response = client.get(f"/containers/{container_id}", headers=user2_headers)
    assert response.status_code == 404

    # List containers for user2 should be empty (or not include user1's)
    response = client.get("/containers", headers=user2_headers)
    assert response.status_code == 200
    container_ids = [c["container_id"] for c in response.json()]
    assert container_id not in container_ids
