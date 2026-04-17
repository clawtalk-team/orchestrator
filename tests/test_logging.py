"""
Tests for logging behaviour added in feat/orchestrator-logging.

Verifies that:
- HTTP request/response middleware emits structured log lines
- Auth middleware logs success and failure paths
- Container creation steps are logged at INFO level
- ECS failures (no tasks returned, failures list) are logged at ERROR level
- EventBridge RUNNING events without an IP log a WARNING
- EventBridge STOPPED events log the stop code/reason
"""

import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.container import Container
from app.services import dynamodb, ecs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TASK_ARN = "arn:aws:ecs:us-east-1:123456789:task/test-cluster/abc123def456"


def _make_container(container_id="oc-log-test", user_id="user-log", status="PENDING"):
    now = datetime.now(timezone.utc)
    return Container(
        container_id=container_id,
        user_id=user_id,
        task_arn=_TASK_ARN,
        status=status,
        health_status="UNKNOWN",
        created_at=now,
        updated_at=now,
    )


def _auth_mock():
    """Return a mock get_auth_client that always authenticates as test-user."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"user_id": "test-user"}
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    return mock_client


# ---------------------------------------------------------------------------
# HTTP request/response middleware logging
# ---------------------------------------------------------------------------

class TestRequestLogging:
    @patch("app.middleware.auth.get_auth_client")
    def test_request_logged_with_method_path_status(
        self, mock_get_auth_client, client, caplog
    ):
        """Each HTTP request logs method, path, status, user, duration."""
        mock_get_auth_client.return_value = _auth_mock()

        with caplog.at_level(logging.INFO, logger="app.main"):
            client.get("/config", headers={"Authorization": "Bearer test-api-key"})

        log_messages = [r.message for r in caplog.records if r.name == "app.main"]
        assert any("GET" in m and "/config" in m and "200" in m for m in log_messages), (
            f"Expected GET /config 200 log, got: {log_messages}"
        )

    def test_public_health_endpoint_logged(self, client, caplog):
        """Health endpoint requests are also logged (no auth required)."""
        with caplog.at_level(logging.INFO, logger="app.main"):
            client.get("/health")

        log_messages = [r.message for r in caplog.records if r.name == "app.main"]
        assert any("/health" in m for m in log_messages)

    @patch("app.middleware.auth.get_auth_client")
    def test_log_includes_user_id(self, mock_get_auth_client, client, caplog):
        """Request log line includes the resolved user_id."""
        mock_get_auth_client.return_value = _auth_mock()

        with caplog.at_level(logging.INFO, logger="app.main"):
            client.get("/config", headers={"Authorization": "Bearer test-api-key"})

        log_messages = [r.message for r in caplog.records if r.name == "app.main"]
        assert any("test-user" in m for m in log_messages)

    def test_unauthenticated_request_logged_with_dash_user(self, client, caplog):
        """Unauthenticated requests log user=- (no user resolved)."""
        with caplog.at_level(logging.INFO, logger="app.main"):
            client.get("/health")

        log_messages = [r.message for r in caplog.records if r.name == "app.main"]
        assert any("user=-" in m for m in log_messages)


# ---------------------------------------------------------------------------
# Auth middleware logging
# ---------------------------------------------------------------------------

class TestAuthLogging:
    @patch("app.middleware.auth.get_auth_client")
    def test_successful_auth_logged(self, mock_get_auth_client, client, caplog):
        """Successful auth logs user_id and path at INFO."""
        mock_get_auth_client.return_value = _auth_mock()

        with caplog.at_level(logging.INFO, logger="app.middleware.auth"):
            client.get("/config", headers={"Authorization": "Bearer test-api-key"})

        auth_logs = [r.message for r in caplog.records if r.name == "app.middleware.auth"]
        assert any("auth ok" in m and "test-user" in m for m in auth_logs)

    @patch("app.middleware.auth.get_auth_client")
    def test_rejected_auth_logged_as_warning(self, mock_get_auth_client, client, caplog):
        """Auth-gateway rejection is logged at WARNING level."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {}
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_auth_client.return_value = mock_client

        with caplog.at_level(logging.WARNING, logger="app.middleware.auth"):
            client.get("/config", headers={"Authorization": "Bearer bad-key"})

        auth_logs = [r for r in caplog.records if r.name == "app.middleware.auth"]
        assert any(r.levelno == logging.WARNING and "auth rejected" in r.message for r in auth_logs)

    @patch("app.middleware.auth.get_auth_client")
    def test_auth_timeout_logged_as_error(self, mock_get_auth_client, client, caplog):
        """Auth-gateway timeout is logged at ERROR level."""
        import httpx
        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        mock_get_auth_client.return_value = mock_client

        with caplog.at_level(logging.ERROR, logger="app.middleware.auth"):
            client.get("/config", headers={"Authorization": "Bearer test-key"})

        auth_logs = [r for r in caplog.records if r.name == "app.middleware.auth"]
        assert any(r.levelno == logging.ERROR and "timeout" in r.message for r in auth_logs)

    @patch("app.middleware.auth.get_auth_client")
    def test_missing_user_id_in_auth_response_logged_as_error(
        self, mock_get_auth_client, client, caplog
    ):
        """Auth response missing user_id is logged at ERROR."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}  # No user_id
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_auth_client.return_value = mock_client

        with caplog.at_level(logging.ERROR, logger="app.middleware.auth"):
            client.get("/config", headers={"Authorization": "Bearer test-key"})

        auth_logs = [r for r in caplog.records if r.name == "app.middleware.auth"]
        assert any(r.levelno == logging.ERROR for r in auth_logs)


# ---------------------------------------------------------------------------
# ECS create_container logging
# ---------------------------------------------------------------------------

class TestECSLogging:
    @patch("app.services.ecs._get_ecs_client")
    @patch("app.services.user_config.UserConfigService.save_user_config")
    @patch("app.services.user_config.UserConfigService.get_user_config")
    def test_create_container_logs_lifecycle_steps(
        self, mock_get_config, mock_save_config, mock_get_ecs, aws_mocks, caplog
    ):
        """create_container logs start, config save, DB write, ECS launch, and completion."""
        mock_get_config.return_value = {}
        mock_save_config.return_value = {"created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z"}

        mock_ecs_client = MagicMock()
        mock_ecs_client.run_task.return_value = {
            "tasks": [{"taskArn": "arn:aws:ecs:us-east-1:123:task/abc123"}],
            "failures": [],
        }
        mock_get_ecs.return_value = mock_ecs_client

        with caplog.at_level(logging.INFO, logger="app.services.ecs"):
            ecs.create_container(user_id="user-123", api_key="test-key")

        ecs_logs = [r.message for r in caplog.records if r.name == "app.services.ecs"]

        assert any("create_container start" in m for m in ecs_logs)
        assert any("config saved" in m for m in ecs_logs)
        assert any("db record created" in m for m in ecs_logs)
        assert any("ECS task launched" in m for m in ecs_logs)
        assert any("create_container complete" in m for m in ecs_logs)

    @patch("app.services.ecs._get_ecs_client")
    @patch("app.services.user_config.UserConfigService.save_user_config")
    @patch("app.services.user_config.UserConfigService.get_user_config")
    def test_ecs_failures_list_logged_as_error(
        self, mock_get_config, mock_save_config, mock_get_ecs, aws_mocks, caplog
    ):
        """ECS failures list in run_task response is logged at ERROR."""
        mock_get_config.return_value = {}
        mock_save_config.return_value = {"created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z"}

        mock_ecs_client = MagicMock()
        mock_ecs_client.run_task.return_value = {
            "tasks": [],
            "failures": [{"arn": "...", "reason": "RESOURCE:MEMORY"}],
        }
        mock_get_ecs.return_value = mock_ecs_client

        with caplog.at_level(logging.ERROR, logger="app.services.ecs"):
            ecs.create_container(user_id="user-123", api_key="test-key")

        ecs_logs = [r for r in caplog.records if r.name == "app.services.ecs"]
        assert any(r.levelno == logging.ERROR and "failures" in r.message for r in ecs_logs)

    @patch("app.services.ecs._get_ecs_client")
    @patch("app.services.user_config.UserConfigService.save_user_config")
    @patch("app.services.user_config.UserConfigService.get_user_config")
    def test_ecs_exception_logged_and_status_set_to_failed(
        self, mock_get_config, mock_save_config, mock_get_ecs, aws_mocks, caplog
    ):
        """ECS exception is logged and container marked FAILED."""
        mock_get_config.return_value = {}
        mock_save_config.return_value = {"created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z"}

        mock_ecs_client = MagicMock()
        mock_ecs_client.run_task.side_effect = Exception("ECS unavailable")
        mock_get_ecs.return_value = mock_ecs_client

        with caplog.at_level(logging.ERROR, logger="app.services.ecs"):
            with pytest.raises(Exception):
                ecs.create_container(user_id="user-123", api_key="test-key")

        ecs_logs = [r for r in caplog.records if r.name == "app.services.ecs"]
        assert any(r.levelno == logging.ERROR and "ECS error" in r.message for r in ecs_logs)


# ---------------------------------------------------------------------------
# ECS handle_task_event logging
# ---------------------------------------------------------------------------

class TestTaskEventLogging:
    def test_running_event_with_ip_logs_ip_at_info(self, aws_mocks, caplog):
        """RUNNING event with ENI attachment logs the extracted IP at INFO."""
        container = _make_container()
        dynamodb.create_container(container)

        event = {
            "detail": {
                "taskArn": _TASK_ARN,
                "lastStatus": "RUNNING",
                "tags": [
                    {"key": "user_id", "value": "user-log"},
                    {"key": "container_id", "value": "oc-log-test"},
                ],
                "attachments": [
                    {
                        "type": "ElasticNetworkInterface",
                        "details": [{"name": "privateIPv4Address", "value": "10.0.1.99"}],
                    }
                ],
            }
        }

        with caplog.at_level(logging.INFO, logger="app.services.ecs"):
            ecs.handle_task_event(event)

        ecs_logs = [r.message for r in caplog.records if r.name == "app.services.ecs"]
        assert any("10.0.1.99" in m for m in ecs_logs)

    def test_running_event_without_ip_logs_warning(self, aws_mocks, caplog):
        """RUNNING event with no ENI attachment logs a WARNING about missing IP."""
        container = _make_container()
        dynamodb.create_container(container)

        event = {
            "detail": {
                "taskArn": _TASK_ARN,
                "lastStatus": "RUNNING",
                "tags": [
                    {"key": "user_id", "value": "user-log"},
                    {"key": "container_id", "value": "oc-log-test"},
                ],
                # No attachments — simulates the bug seen with oc-bce981d3
            }
        }

        with caplog.at_level(logging.WARNING, logger="app.services.ecs"):
            ecs.handle_task_event(event)

        ecs_logs = [r for r in caplog.records if r.name == "app.services.ecs"]
        assert any(
            r.levelno == logging.WARNING and "no IP" in r.message
            for r in ecs_logs
        ), f"Expected warning about missing IP, got: {[r.message for r in ecs_logs]}"

    def test_stopped_event_logs_reason(self, aws_mocks, caplog):
        """STOPPED event logs the stop code and reason."""
        container = _make_container(status="RUNNING")
        dynamodb.create_container(container)

        event = {
            "detail": {
                "taskArn": _TASK_ARN,
                "lastStatus": "STOPPED",
                "stopCode": "TaskFailedToStart",
                "stoppedReason": "Essential container in task exited",
                "tags": [
                    {"key": "user_id", "value": "user-log"},
                    {"key": "container_id", "value": "oc-log-test"},
                ],
            }
        }

        with caplog.at_level(logging.INFO, logger="app.services.ecs"):
            ecs.handle_task_event(event)

        ecs_logs = [r.message for r in caplog.records if r.name == "app.services.ecs"]
        assert any("TaskFailedToStart" in m for m in ecs_logs)
        assert any("Essential container" in m for m in ecs_logs)


# ---------------------------------------------------------------------------
# DynamoDB operation logging
# ---------------------------------------------------------------------------

class TestDynamoDBLogging:
    def test_create_container_logged(self, aws_mocks, caplog):
        """dynamodb.create_container logs at INFO."""
        container = _make_container("oc-db-log-1")

        with caplog.at_level(logging.INFO, logger="app.services.dynamodb"):
            dynamodb.create_container(container)

        db_logs = [r.message for r in caplog.records if r.name == "app.services.dynamodb"]
        assert any("create_container" in m and "oc-db-log-1" in m for m in db_logs)

    def test_update_container_logged_with_status(self, aws_mocks, caplog):
        """dynamodb.update_container logs container_id, status and health."""
        container = _make_container("oc-db-log-2")
        dynamodb.create_container(container)
        container.status = "RUNNING"
        container.health_status = "STARTING"

        with caplog.at_level(logging.INFO, logger="app.services.dynamodb"):
            dynamodb.update_container(container)

        db_logs = [r.message for r in caplog.records if r.name == "app.services.dynamodb"]
        assert any(
            "update_container" in m and "RUNNING" in m and "STARTING" in m
            for m in db_logs
        )
