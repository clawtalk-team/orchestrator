import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from moto import mock_aws
import boto3

# Set up environment for testing
# Don't set DYNAMODB_ENDPOINT - let moto intercept boto3 calls
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["ECS_CLUSTER_NAME"] = "test-cluster"
os.environ["ECS_TASK_DEFINITION"] = "test-task"
os.environ["ECS_CONTAINER_NAME"] = "test-container"


@pytest.fixture
def aws_mocks():
    """Set up mocked AWS services."""
    with mock_aws():
        from app.services.dynamodb import ensure_table_exists

        # Set up DynamoDB table
        ensure_table_exists()

        # Set up ECS cluster
        ecs = boto3.client("ecs", region_name="us-east-1")
        ecs.create_cluster(clusterName="test-cluster")

        # Register task definition
        ecs.register_task_definition(
            family="test-task",
            networkMode="awsvpc",
            requiresCompatibilities=["FARGATE"],
            cpu="256",
            memory="512",
            containerDefinitions=[
                {
                    "name": "test-container",
                    "image": "openclaw-agent:latest",
                    "portMappings": [
                        {
                            "containerPort": 8080,
                            "hostPort": 8080,
                            "protocol": "tcp",
                        }
                    ],
                }
            ],
        )

        yield


@pytest.fixture
def client(aws_mocks):
    """Test client with mocked AWS services."""
    from app.main import app

    return TestClient(app)


@pytest.fixture
def authenticated_client(aws_mocks):
    """Test client with authentication header."""
    from app.main import app

    client = TestClient(app)
    client.headers.update({"Authorization": "Bearer test-user:test-token-value"})
    return client
