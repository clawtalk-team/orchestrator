"""Integration tests for container lifecycle — ECS and k8s backends."""
import os

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


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test-user-123:test-token-abc123"}


# ---------------------------------------------------------------------------
# Backend-parametrized fixture
# ---------------------------------------------------------------------------

@pytest.fixture(params=["ecs", "k8s"])
def backend(request, mock_k8s):
    """Run each test against both ECS and k8s backends.

    mock_k8s is included so the k8s API is always mocked; it is a no-op for
    ECS-backend calls.
    """
    return request.param


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------

def _create_container(client, auth_headers, backend: str, name: str = "test-container"):
    return client.post(
        "/containers",
        json={"name": name, "backend": backend},
        headers=auth_headers,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_create_container(client, auth_headers, backend):
    response = _create_container(client, auth_headers, backend)

    assert response.status_code == 200
    data = response.json()
    assert "container_id" in data
    assert data["status"] in ["PENDING", "RUNNING"]
    assert data["backend"] == backend

    # Verify container is in DynamoDB
    container = dynamodb.get_container("test-user-123", data["container_id"])
    assert container is not None
    assert container.user_id == "test-user-123"
    assert container.backend == backend


def test_list_containers(client, auth_headers, backend):
    create_resp = _create_container(client, auth_headers, backend, name="test-list")
    assert create_resp.status_code == 200

    response = client.get("/containers", headers=auth_headers)
    assert response.status_code == 200

    containers = response.json()
    assert isinstance(containers, list)
    container_ids = [c["container_id"] for c in containers]
    assert create_resp.json()["container_id"] in container_ids


def test_get_container(client, auth_headers, backend):
    create_resp = _create_container(client, auth_headers, backend, name="test-get")
    container_id = create_resp.json()["container_id"]

    response = client.get(f"/containers/{container_id}", headers=auth_headers)
    assert response.status_code == 200

    data = response.json()
    assert data["container_id"] == container_id
    assert data["backend"] == backend


def test_get_container_not_found(client, auth_headers):
    response = client.get("/containers/nonexistent-id", headers=auth_headers)
    assert response.status_code == 404


def test_delete_container(client, auth_headers, backend):
    create_resp = _create_container(client, auth_headers, backend, name="test-delete")
    container_id = create_resp.json()["container_id"]

    response = client.delete(f"/containers/{container_id}", headers=auth_headers)
    assert response.status_code == 204


def test_get_container_health(client, auth_headers, backend):
    create_resp = _create_container(client, auth_headers, backend, name="test-health")
    container_id = create_resp.json()["container_id"]

    response = client.get(f"/containers/{container_id}/health", headers=auth_headers)
    assert response.status_code == 200

    data = response.json()
    assert data["container_id"] == container_id
    assert "health_status" in data


def test_user_isolation(client):
    """Users cannot see each other's containers regardless of backend."""
    user1_headers = {"Authorization": "Bearer user1:token1"}
    create_resp = client.post(
        "/containers",
        json={"name": "user1-container"},
        headers=user1_headers,
    )
    container_id = create_resp.json()["container_id"]

    user2_headers = {"Authorization": "Bearer user2:token2"}
    assert client.get(f"/containers/{container_id}", headers=user2_headers).status_code == 404

    container_ids = [c["container_id"] for c in client.get("/containers", headers=user2_headers).json()]
    assert container_id not in container_ids
