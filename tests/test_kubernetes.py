"""Tests for the Kubernetes service — mirrors tests/test_ecs.py structure."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.container import Container
from app.services import kubernetes as k8s_service


# ── ID generation ─────────────────────────────────────────────────────────────

def test_generate_container_id():
    """Container IDs match the shared oc-{8hex} format."""
    container_id = k8s_service._generate_container_id()
    assert container_id.startswith("oc-")
    assert len(container_id) == 11  # "oc-" + 8 hex chars


# ── Endpoint extraction ───────────────────────────────────────────────────────

def test_extract_pod_endpoint():
    """IP extracted from a running Pod SDK object."""
    mock_pod = MagicMock()
    mock_pod.status.pod_ip = "10.42.0.5"

    result = k8s_service.extract_pod_endpoint(mock_pod)

    assert result is not None
    assert result["ip_address"] == "10.42.0.5"
    assert result["port"] == 8080
    assert result["health_endpoint"] == "http://10.42.0.5:8080/health"
    assert result["api_endpoint"] == "http://10.42.0.5:8080"


def test_extract_pod_endpoint_dict():
    """IP extracted from a plain-dict Pod representation."""
    pod = {"status": {"podIP": "10.42.0.7"}}
    result = k8s_service.extract_pod_endpoint(pod)
    assert result is not None
    assert result["ip_address"] == "10.42.0.7"


def test_extract_pod_endpoint_no_ip():
    """Returns None when pod has no IP yet."""
    mock_pod = MagicMock()
    mock_pod.status.pod_ip = None

    result = k8s_service.extract_pod_endpoint(mock_pod)

    assert result is None


def test_extract_pod_endpoint_no_status():
    """Returns None when pod has no status."""
    pod = {}
    result = k8s_service.extract_pod_endpoint(pod)
    assert result is None


# ── Container creation ────────────────────────────────────────────────────────

def test_create_container(aws_mocks):
    """create_container records PENDING status and stores pod name in task_arn."""
    mock_result = MagicMock()
    mock_result.metadata.name = "oc-test1234"

    with patch("app.services.kubernetes._get_k8s_client") as mock_get:
        mock_api = MagicMock()
        mock_api.create_namespaced_pod.return_value = mock_result
        mock_get.return_value = mock_api

        container = k8s_service.create_container(
            user_id="user-123",
            api_key="test-token",
            config_name="default",
            agent_id="agent-abc",
        )

    assert container.status == "PENDING"
    assert container.backend == "k8s"
    assert container.task_arn == "oc-test1234"
    assert container.container_id.startswith("oc-")
    mock_api.create_namespaced_pod.assert_called_once()

    # Verify env vars were set correctly
    call_kwargs = mock_api.create_namespaced_pod.call_args
    pod_body = call_kwargs[1]["body"] if call_kwargs[1] else call_kwargs[0][1]
    env_names = {e.name for e in pod_body.spec.containers[0].env}
    assert "API_KEY" in env_names
    assert "CONTAINER_ID" in env_names
    assert "AGENT_ID" in env_names
    assert "ORCHESTRATOR_URL" in env_names


def test_create_container_protected_env_vars(aws_mocks):
    """User-supplied env vars cannot override protected keys."""
    mock_result = MagicMock()
    mock_result.metadata.name = "oc-test9999"

    with patch("app.services.kubernetes._get_k8s_client") as mock_get:
        mock_api = MagicMock()
        mock_api.create_namespaced_pod.return_value = mock_result
        mock_get.return_value = mock_api

        k8s_service.create_container(
            user_id="user-123",
            api_key="real-token",
            env_vars={"API_KEY": "hacked", "CUSTOM_VAR": "allowed"},
            agent_id="agent-abc",
        )

    pod_body = mock_api.create_namespaced_pod.call_args[1]["body"]
    env_vars = pod_body.spec.containers[0].env
    plain_map = {e.name: e.value for e in env_vars}

    # API_KEY is a plain env var (matching ECS behaviour); user cannot override it
    assert plain_map.get("API_KEY") == "real-token"
    assert plain_map["CUSTOM_VAR"] == "allowed"  # custom var passed through


def test_create_container_api_failure(aws_mocks):
    """If the k8s API call fails with ApiException the container record is marked FAILED."""
    from kubernetes.client.exceptions import ApiException

    from app.services import dynamodb

    with patch("app.services.kubernetes._get_k8s_client") as mock_get:
        mock_api = MagicMock()
        mock_api.create_namespaced_pod.side_effect = ApiException(status=500, reason="Internal Server Error")
        mock_get.return_value = mock_api

        with pytest.raises(ApiException):
            k8s_service.create_container(
                user_id="user-fail",
                api_key="tok",
                agent_id="agent-abc",
            )

    # The record written before the API call should be marked FAILED
    from app.services.dynamodb import get_user_containers
    containers = get_user_containers("user-fail")
    assert len(containers) == 1
    assert containers[0].status == "FAILED"


def test_create_container_connection_error_marks_failed(aws_mocks):
    """If the k8s API call fails with a connection error the container is marked FAILED.

    urllib3.MaxRetryError is not an ApiException; the old code let it escape
    without updating DynamoDB.  The fix broadens the except to Exception.
    """
    import urllib3.exceptions

    with patch("app.services.kubernetes._get_k8s_client") as mock_get:
        mock_api = MagicMock()
        mock_api.create_namespaced_pod.side_effect = urllib3.exceptions.MaxRetryError(
            pool=None, url="/api/v1/namespaces/openclaw/pods"
        )
        mock_get.return_value = mock_api

        with pytest.raises(urllib3.exceptions.MaxRetryError):
            k8s_service.create_container(
                user_id="user-connfail",
                api_key="tok",
                agent_id="agent-abc",
            )

    from app.services.dynamodb import get_user_containers
    containers = get_user_containers("user-connfail")
    assert len(containers) == 1
    assert containers[0].status == "FAILED"


def test_load_kubeconfig_from_ssm_uses_load_kube_config_from_dict(monkeypatch):
    """_load_kubeconfig_from_ssm must call load_kube_config_from_dict, not
    load_kube_config(config_dict=...).  The latter is unavailable in some
    kubernetes-client versions and raises TypeError."""
    import yaml
    from kubernetes import config as k8s_config

    sample_kubeconfig = {
        "apiVersion": "v1",
        "clusters": [{"cluster": {"server": "https://100.93.150.95:6443"}, "name": "default"}],
        "contexts": [{"context": {"cluster": "default", "user": "default"}, "name": "default"}],
        "current-context": "default",
        "kind": "Config",
        "users": [{"name": "default", "user": {}}],
    }

    captured = {}

    def fake_ssm_get(Name, WithDecryption):
        return {"Parameter": {"Value": yaml.dump(sample_kubeconfig)}}

    def fake_load_from_dict(config_dict, context=None, **kwargs):
        captured["called"] = True
        captured["context"] = context

    monkeypatch.setenv("AWS_REGION", "ap-southeast-2")

    with patch("boto3.client") as mock_boto3, \
         patch.object(k8s_config, "load_kube_config_from_dict", fake_load_from_dict):
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.side_effect = fake_ssm_get
        mock_boto3.return_value = mock_ssm

        result = k8s_service._load_kubeconfig_from_ssm("/test/path", "default")

    assert result is True
    assert captured.get("called") is True
    assert captured["context"] == "default"


# ── Stop container ────────────────────────────────────────────────────────────

def test_stop_container(aws_mocks):
    """stop_container deletes the pod and updates DynamoDB to STOPPED."""
    from app.services import dynamodb

    now = datetime.utcnow()
    container = Container(
        container_id="oc-stop01",
        user_id="user-123",
        task_arn="oc-stop01",
        status="RUNNING",
        health_status="HEALTHY",
        backend="k8s",
        created_at=now,
        updated_at=now,
    )
    dynamodb.create_container(container)

    with patch("app.services.kubernetes._get_k8s_client") as mock_get:
        mock_api = MagicMock()
        mock_get.return_value = mock_api

        result = k8s_service.stop_container("user-123", "oc-stop01")

    assert result is True
    mock_api.delete_namespaced_pod.assert_called_once()

    updated = dynamodb.get_container("user-123", "oc-stop01")
    assert updated.status == "STOPPED"


def test_stop_container_pod_already_gone(aws_mocks):
    """stop_container succeeds gracefully when pod is already deleted (404)."""
    from kubernetes.client.exceptions import ApiException

    from app.services import dynamodb

    now = datetime.utcnow()
    container = Container(
        container_id="oc-gone01",
        user_id="user-123",
        task_arn="oc-gone01",
        status="RUNNING",
        health_status="HEALTHY",
        backend="k8s",
        created_at=now,
        updated_at=now,
    )
    dynamodb.create_container(container)

    with patch("app.services.kubernetes._get_k8s_client") as mock_get:
        mock_api = MagicMock()
        mock_api.delete_namespaced_pod.side_effect = ApiException(status=404, reason="Not Found")
        mock_get.return_value = mock_api

        result = k8s_service.stop_container("user-123", "oc-gone01")

    assert result is True
    updated = dynamodb.get_container("user-123", "oc-gone01")
    assert updated.status == "STOPPED"


def test_stop_container_not_in_db(aws_mocks):
    """stop_container returns False when container isn't in DynamoDB."""
    result = k8s_service.stop_container("user-123", "oc-nonexistent")
    assert result is False


# ── Status sync ───────────────────────────────────────────────────────────────

def test_sync_pod_status_running(aws_mocks):
    """sync_pod_status updates to RUNNING and extracts pod IP."""
    from app.services import dynamodb

    now = datetime.utcnow()
    container = Container(
        container_id="oc-sync01",
        user_id="user-123",
        task_arn="oc-sync01",
        status="PENDING",
        health_status="UNKNOWN",
        backend="k8s",
        created_at=now,
        updated_at=now,
    )
    dynamodb.create_container(container)

    mock_pod = MagicMock()
    mock_pod.status.phase = "Running"
    mock_pod.status.pod_ip = "10.42.0.12"

    with patch("app.services.kubernetes._get_k8s_client") as mock_get:
        mock_api = MagicMock()
        mock_api.read_namespaced_pod.return_value = mock_pod
        mock_get.return_value = mock_api

        result = k8s_service.sync_pod_status("user-123", "oc-sync01")

    assert result.status == "RUNNING"
    assert result.health_status == "STARTING"
    assert result.ip_address == "10.42.0.12"
    assert result.health_endpoint == "http://10.42.0.12:8080/health"
    assert result.api_endpoint == "http://10.42.0.12:8080"

    # Persisted to DynamoDB
    updated = dynamodb.get_container("user-123", "oc-sync01")
    assert updated.status == "RUNNING"
    assert updated.ip_address == "10.42.0.12"


def test_sync_pod_status_failed(aws_mocks):
    """sync_pod_status marks container STOPPED when pod phase is Failed."""
    from app.services import dynamodb

    now = datetime.utcnow()
    container = Container(
        container_id="oc-fail01",
        user_id="user-123",
        task_arn="oc-fail01",
        status="RUNNING",
        health_status="UNHEALTHY",
        backend="k8s",
        created_at=now,
        updated_at=now,
    )
    dynamodb.create_container(container)

    mock_pod = MagicMock()
    mock_pod.status.phase = "Failed"
    mock_pod.status.pod_ip = None

    with patch("app.services.kubernetes._get_k8s_client") as mock_get:
        mock_api = MagicMock()
        mock_api.read_namespaced_pod.return_value = mock_pod
        mock_get.return_value = mock_api

        result = k8s_service.sync_pod_status("user-123", "oc-fail01")

    assert result.status == "STOPPED"


def test_sync_pod_status_pod_missing(aws_mocks):
    """sync_pod_status marks STOPPED when pod is deleted (404)."""
    from kubernetes.client.exceptions import ApiException

    from app.services import dynamodb

    now = datetime.utcnow()
    container = Container(
        container_id="oc-del01",
        user_id="user-123",
        task_arn="oc-del01",
        status="RUNNING",
        health_status="STARTING",
        backend="k8s",
        created_at=now,
        updated_at=now,
    )
    dynamodb.create_container(container)

    with patch("app.services.kubernetes._get_k8s_client") as mock_get:
        mock_api = MagicMock()
        mock_api.read_namespaced_pod.side_effect = ApiException(status=404, reason="Not Found")
        mock_get.return_value = mock_api

        result = k8s_service.sync_pod_status("user-123", "oc-del01")

    assert result.status == "STOPPED"


# ── Route-level tests ─────────────────────────────────────────────────────────

def _mock_auth():
    """Return a patch context that makes the auth middleware accept any Bearer token."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"user_id": "test-user"}
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    return patch("app.middleware.auth.get_auth_client", return_value=mock_client)


@_mock_auth()
def test_post_containers_k8s_backend(aws_mocks):
    """POST /containers with backend=k8s creates a k8s-backed container."""
    from app.main import app
    from fastapi.testclient import TestClient

    mock_result = MagicMock()
    mock_result.metadata.name = "oc-routek8s"

    with patch("app.services.kubernetes._get_k8s_client") as mock_get:
        mock_api = MagicMock()
        mock_api.create_namespaced_pod.return_value = mock_result
        mock_get.return_value = mock_api

        client = TestClient(app)
        client.headers.update({"Authorization": "Bearer test-user:test-token-value"})

        response = client.post(
            "/containers",
            json={"agent_id": "agent-k8s-test", "backend": "k8s"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "PENDING"
    assert data["backend"] == "k8s"
    assert data["container_id"].startswith("oc-")
    mock_api.create_namespaced_pod.assert_called_once()


@_mock_auth()
def test_post_containers_k8s_backend_default(aws_mocks):
    """POST /containers without backend uses k8s (server default)."""
    from app.main import app
    from fastapi.testclient import TestClient

    mock_result = MagicMock()
    mock_result.metadata.name = "oc-default-k8s"

    with patch("app.services.kubernetes._get_k8s_client") as mock_get, \
         patch("app.services.kubernetes._update_agent_container"):
        mock_api = MagicMock()
        mock_api.create_namespaced_pod.return_value = mock_result
        mock_get.return_value = mock_api

        client = TestClient(app)
        client.headers.update({"Authorization": "Bearer test-user:test-token-value"})

        response = client.post(
            "/containers",
            json={"agent_id": "agent-k8s-default"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["backend"] == "k8s"
    mock_api.create_namespaced_pod.assert_called_once()


@_mock_auth()
def test_delete_container_k8s(aws_mocks):
    """DELETE /containers/{id} on a k8s container deletes the pod."""
    from datetime import timezone

    from app.main import app
    from fastapi.testclient import TestClient

    from app.services import dynamodb

    now = datetime.now(timezone.utc)
    container = Container(
        container_id="oc-del-rt",
        user_id="test-user",
        task_arn="oc-del-rt",
        status="RUNNING",
        health_status="HEALTHY",
        backend="k8s",
        created_at=now,
        updated_at=now,
    )
    dynamodb.create_container(container)

    with patch("app.services.kubernetes._get_k8s_client") as mock_get:
        mock_api = MagicMock()
        mock_get.return_value = mock_api

        client = TestClient(app)
        client.headers.update({"Authorization": "Bearer test-user:test-token-value"})
        response = client.delete("/containers/oc-del-rt")

    assert response.status_code == 204
    mock_api.delete_namespaced_pod.assert_called_once()
