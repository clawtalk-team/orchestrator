"""Integration test configuration and fixtures."""

import os
import time
from unittest.mock import MagicMock, patch

import pytest

from tests.fixtures.mock_auth_gateway import MockAuthGateway


@pytest.fixture(scope="module", autouse=True)
def setup_integration_environment():
    """Set up environment for integration tests."""
    # ECS settings (used when backend=ecs)
    os.environ["ECS_CLUSTER_NAME"] = "test-cluster"
    os.environ["ECS_TASK_DEFINITION"] = "test-task"
    os.environ["ECS_CONTAINER_NAME"] = "test-container"
    os.environ["ECS_SUBNETS"] = "subnet-12345"
    os.environ["ECS_SECURITY_GROUPS"] = "sg-12345"

    # k8s settings (used when backend=k8s)
    os.environ["K8S_NAMESPACE"] = "openclaw"
    os.environ["K8S_IMAGE"] = "openclaw-agent:test"
    os.environ["K8S_IMAGE_PULL_POLICY"] = "Never"

    from app.config import get_settings
    get_settings.cache_clear()

    yield

    get_settings.cache_clear()


@pytest.fixture(scope="module", autouse=True)
def mock_auth_gateway():
    """Start mock auth gateway for integration tests."""
    gateway = MockAuthGateway(host="localhost", port=8001)
    gateway.start()
    time.sleep(0.5)

    os.environ["AUTH_GATEWAY_URL"] = gateway.url

    from app.config import get_settings
    get_settings.cache_clear()

    yield gateway

    gateway.stop()
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def mock_ecs():
    """Mock ECS client for integration tests."""
    with patch("app.services.ecs._get_ecs_client") as mock_ecs_client, \
         patch("app.services.ecs._update_agent_container"):
        mock_client = MagicMock()
        mock_client.run_task.return_value = {
            "tasks": [
                {
                    "taskArn": "arn:aws:ecs:us-east-1:123456789012:task/test-cluster/abc123",
                    "lastStatus": "PENDING",
                    "desiredStatus": "RUNNING",
                }
            ]
        }
        mock_ecs_client.return_value = mock_client
        yield mock_client


@pytest.fixture()
def mock_k8s():
    """Mock Kubernetes client for integration tests."""
    # Reset module-level cached client before each test
    import app.services.kubernetes as k8s_service
    original_client = k8s_service._k8s_core_v1
    k8s_service._k8s_core_v1 = None

    with patch("app.services.kubernetes._get_k8s_client") as mock_get, \
         patch("app.services.kubernetes._update_agent_container"):
        mock_api = MagicMock()

        # Mock pod creation
        mock_pod_result = MagicMock()
        mock_pod_result.metadata.name = "oc-k8stest1"
        mock_api.create_namespaced_pod.return_value = mock_pod_result

        # Mock pod read (for sync_pod_status)
        mock_pod_status = MagicMock()
        mock_pod_status.status.phase = "Running"
        mock_pod_status.status.pod_ip = "10.42.0.99"
        mock_api.read_namespaced_pod.return_value = mock_pod_status

        mock_get.return_value = mock_api
        yield mock_api

    k8s_service._k8s_core_v1 = original_client
