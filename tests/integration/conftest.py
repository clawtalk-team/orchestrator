"""Integration test configuration and fixtures."""

import os
import time
from unittest.mock import MagicMock, patch

import pytest

from tests.fixtures.mock_auth_gateway import MockAuthGateway


@pytest.fixture(scope="module", autouse=True)
def setup_integration_environment():
    """Set up environment for integration tests."""
    # Set ECS environment variables
    os.environ["ECS_CLUSTER_NAME"] = "test-cluster"
    os.environ["ECS_TASK_DEFINITION"] = "test-task"
    os.environ["ECS_CONTAINER_NAME"] = "test-container"
    os.environ["ECS_SUBNETS"] = "subnet-12345"
    os.environ["ECS_SECURITY_GROUPS"] = "sg-12345"

    # Clear settings cache to pick up new env vars
    from app.config import get_settings

    get_settings.cache_clear()

    yield

    # Cleanup
    get_settings.cache_clear()


@pytest.fixture(scope="module", autouse=True)
def mock_auth_gateway():
    """Start mock auth gateway for integration tests.

    This fixture automatically starts a mock auth gateway server
    on localhost:8001 for all integration tests.
    """
    gateway = MockAuthGateway(host="localhost", port=8001)
    gateway.start()

    # Give the server a moment to start
    time.sleep(0.5)

    # Set environment variable for the app to use
    os.environ["AUTH_GATEWAY_URL"] = gateway.url

    # Clear settings cache to pick up new env var
    from app.config import get_settings

    get_settings.cache_clear()

    yield gateway

    # Cleanup
    gateway.stop()
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def mock_ecs():
    """Mock ECS client for integration tests."""
    with patch("app.services.ecs._get_ecs_client") as mock_ecs_client:
        # Create a mock ECS client that returns successful responses
        mock_client = MagicMock()

        # Mock run_task to return a successful task creation
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
