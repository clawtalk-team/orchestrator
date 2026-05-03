"""Kubernetes backend for container orchestration.

Mirrors the interface of app.services.ecs so the route layer can swap
between ECS and k8s with a single conditional.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from kubernetes.client.exceptions import ApiException

from app.config import get_settings
from app.models.container import Container
from app.services import dynamodb
from app.services.user_config import UserConfigService

logger = logging.getLogger(__name__)

# Module-level cached client — config is loaded once on first use.
_k8s_core_v1: Optional[k8s_client.CoreV1Api] = None


def _load_kubeconfig_from_ssm(ssm_path: str, context: Optional[str]) -> bool:
    """Fetch kubeconfig YAML from SSM and load it. Returns True on success."""
    try:
        import os

        import boto3
        import yaml

        region = os.environ.get("AWS_REGION") or os.environ.get("DYNAMODB_REGION", "us-east-1")
        ssm = boto3.client("ssm", region_name=region)
        response = ssm.get_parameter(Name=ssm_path, WithDecryption=True)
        kubeconfig_yaml = response["Parameter"]["Value"]
        config_dict = yaml.safe_load(kubeconfig_yaml)
        k8s_config.load_kube_config_from_dict(config_dict, context=context)
        logger.info("k8s kubeconfig loaded from SSM: %s", ssm_path)
        return True
    except Exception as exc:
        logger.warning("k8s kubeconfig SSM load failed (%s): %s", ssm_path, exc)
        return False


def _get_k8s_client() -> k8s_client.CoreV1Api:
    """Return a cached CoreV1Api client, loading kubeconfig on first call."""
    global _k8s_core_v1
    if _k8s_core_v1 is not None:
        return _k8s_core_v1

    settings = get_settings()
    try:
        if settings.k8s_kubeconfig_ssm_path:
            _load_kubeconfig_from_ssm(settings.k8s_kubeconfig_ssm_path, settings.k8s_context)
        elif settings.k8s_kubeconfig:
            k8s_config.load_kube_config(
                config_file=settings.k8s_kubeconfig,
                context=settings.k8s_context,
            )
        else:
            try:
                k8s_config.load_incluster_config()
            except k8s_config.ConfigException:
                k8s_config.load_kube_config(context=settings.k8s_context)
    except Exception as exc:
        logger.warning("k8s config load warning: %s", exc)

    _k8s_core_v1 = k8s_client.CoreV1Api()
    return _k8s_core_v1


def _generate_container_id() -> str:
    return f"oc-{uuid.uuid4().hex[:8]}"


def _update_agent_container(user_id: str, agent_id: str, container_id: str, api_key: str) -> None:
    """Notify auth-gateway of the container assigned to an agent."""
    settings = get_settings()
    url = f"{settings.auth_gateway_url}/users/{user_id}/agents/{agent_id}"
    try:
        response = httpx.put(
            url,
            json={"container_id": container_id},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=settings.auth_gateway_timeout,
        )
        if response.status_code == 200:
            logger.info("agent container updated: agent=%s container=%s", agent_id, container_id)
        else:
            logger.warning(
                "agent container update failed: agent=%s container=%s status=%s body=%s",
                agent_id, container_id, response.status_code, response.text,
            )
    except httpx.RequestError as exc:
        logger.error("agent container update error: agent=%s container=%s error=%s", agent_id, container_id, exc)


def create_container(
    user_id: str,
    api_key: str,
    config_name: str = "default",
    agent_id: Optional[str] = None,
    env_vars: Optional[Dict[str, str]] = None,
) -> Container:
    """Create a new Kubernetes Pod for a user.

    Returns a Container record in PENDING status; the Pod starts asynchronously.
    Call sync_pod_status() to refresh status once the Pod is scheduled.
    """
    settings = get_settings()
    container_id = _generate_container_id()
    now = datetime.now(timezone.utc)

    logger.info("k8s create_container start: container=%s user=%s config=%s", container_id, user_id, config_name)

    # 1. Ensure user config exists with defaults and current API key
    config_service = UserConfigService()
    config_service.ensure_container_defaults(user_id=user_id, config_name=config_name, api_key=api_key)

    # 2. Create Container record in PENDING status
    container = Container(
        container_id=container_id,
        user_id=user_id,
        task_arn="",
        status="PENDING",
        agent_id=agent_id,
        health_status="UNKNOWN",
        backend="k8s",
        created_at=now,
        updated_at=now,
    )
    dynamodb.create_container(container)
    logger.info("k8s create_container db record created: container=%s", container_id)

    # 3. Build environment variables — all plain env vars, matching ECS behaviour.
    #    Also inject the user's LLM provider key so openclaw.json env-var references
    #    (e.g. ${OPENROUTER_API_KEY}) resolve correctly inside the pod.
    namespace = settings.k8s_namespace
    api = _get_k8s_client()

    user_config = config_service.get_user_config(user_id, config_name) or {}
    llm_provider_env_keys = {
        "openrouter": ("OPENROUTER_API_KEY", user_config.get("openrouter_api_key", "")),
        "anthropic": ("ANTHROPIC_API_KEY", user_config.get("anthropic_api_key", "")),
        "openai": ("OPENAI_API_KEY", user_config.get("openai_api_key", "")),
    }

    protected_keys = {
        "API_KEY", "CONTAINER_ID", "CONFIG_NAME", "ORCHESTRATOR_URL", "AGENT_ID", "OPENCLAW_DISABLE_BONJOUR"
    }
    plain_env: Dict[str, str] = {
        "API_KEY": api_key,
        "CONTAINER_ID": container_id,
        "CONFIG_NAME": config_name,
        "ORCHESTRATOR_URL": settings.orchestrator_url,
        "OPENCLAW_DISABLE_BONJOUR": "1",
    }
    if agent_id:
        plain_env["AGENT_ID"] = agent_id

    # Inject all known LLM provider keys so the pod works regardless of which
    # provider the user has configured.
    for env_name, value in llm_provider_env_keys.values():
        if value:
            plain_env[env_name] = value

    if env_vars:
        filtered = {k: v for k, v in env_vars.items() if k not in protected_keys}
        plain_env.update(filtered)
        if filtered:
            logger.info("Added %d custom env vars to container %s", len(filtered), container_id)

    k8s_env = [k8s_client.V1EnvVar(name=k, value=v) for k, v in plain_env.items()]

    # 5. Build Pod manifest
    pod = k8s_client.V1Pod(
        metadata=k8s_client.V1ObjectMeta(
            name=container_id,
            namespace=namespace,
            labels={
                "app": "openclaw-agent",
                "user_id": user_id,
                "container_id": container_id,
            },
        ),
        spec=k8s_client.V1PodSpec(
            restart_policy="Never",
            containers=[
                k8s_client.V1Container(
                    name="openclaw-agent",
                    image=settings.k8s_image,
                    image_pull_policy=settings.k8s_image_pull_policy,
                    ports=[k8s_client.V1ContainerPort(container_port=8080)],
                    env=k8s_env,
                )
            ],
            image_pull_secrets=(
                [k8s_client.V1LocalObjectReference(name=settings.k8s_image_pull_secret)]
                if settings.k8s_image_pull_secret else None
            ),
        ),
    )

    # 6. Create Pod
    try:
        result = api.create_namespaced_pod(
            namespace=namespace, body=pod, _request_timeout=settings.k8s_api_timeout
        )
        pod_name = result.metadata.name
        container.task_arn = pod_name
        container.updated_at = datetime.now(timezone.utc)
        dynamodb.update_container(container)
        logger.info("k8s pod created: container=%s pod=%s namespace=%s", container_id, pod_name, namespace)

        if agent_id:
            _update_agent_container(user_id=user_id, agent_id=agent_id, container_id=container_id, api_key=api_key)
    except Exception as exc:
        logger.exception("k8s pod creation failed: container=%s error=%s", container_id, exc)
        container.status = "FAILED"
        container.updated_at = datetime.now(timezone.utc)
        dynamodb.update_container(container)
        raise

    logger.info("k8s create_container complete: container=%s pod=%s", container_id, container.task_arn)
    return container


def stop_container(user_id: str, container_id: str) -> bool:
    """Delete the Kubernetes Pod backing a container."""
    container = dynamodb.get_container(user_id, container_id)
    if not container:
        return False

    pod_name = container.task_arn or container_id
    settings = get_settings()
    namespace = settings.k8s_namespace

    api = _get_k8s_client()
    try:
        api.delete_namespaced_pod(
            name=pod_name, namespace=namespace, _request_timeout=settings.k8s_api_timeout
        )
        logger.info("k8s pod deleted: container=%s pod=%s", container_id, pod_name)
    except ApiException as exc:
        if exc.status != 404:
            logger.exception("k8s pod deletion failed: container=%s error=%s", container_id, exc)
            return False
        logger.info("k8s pod already gone: container=%s pod=%s", container_id, pod_name)

    container.status = "STOPPED"
    container.updated_at = datetime.now(timezone.utc)
    dynamodb.update_container(container)
    return True


def get_container_details(user_id: str, container_id: str) -> Optional[Container]:
    """Get container details from DynamoDB."""
    return dynamodb.get_container(user_id, container_id)


def extract_pod_endpoint(pod: Any) -> Optional[Dict[str, str]]:
    """Extract connection details from a running Kubernetes Pod object.

    Accepts both a kubernetes SDK V1Pod object and a plain dict (for testing).
    """
    ip: Optional[str] = None
    if hasattr(pod, "status") and pod.status:
        ip = getattr(pod.status, "pod_ip", None)
    elif isinstance(pod, dict):
        ip = pod.get("status", {}).get("podIP")

    if not ip:
        return None

    return {
        "ip_address": ip,
        "port": 8080,
        "health_endpoint": f"http://{ip}:8080/health",
        "api_endpoint": f"http://{ip}:8080",
    }


def sync_pod_status(user_id: str, container_id: str) -> Optional[Container]:
    """Poll the Kubernetes API and sync the container's status in DynamoDB.

    Called on-demand (e.g. GET /containers/{id}) to keep status fresh without
    requiring a cluster-side event webhook.
    """
    container = dynamodb.get_container(user_id, container_id)
    if not container or not container.task_arn:
        return container

    settings = get_settings()
    try:
        api = _get_k8s_client()
        pod = api.read_namespaced_pod(
            name=container.task_arn, namespace=settings.k8s_namespace,
            _request_timeout=settings.k8s_api_timeout,
        )
        phase = pod.status.phase if pod.status else None
        logger.info("k8s sync_pod_status: container=%s pod=%s phase=%s", container_id, container.task_arn, phase)

        if phase == "Running":
            endpoints = extract_pod_endpoint(pod)
            if endpoints:
                container.ip_address = endpoints["ip_address"]
                container.health_endpoint = endpoints["health_endpoint"]
                container.api_endpoint = endpoints["api_endpoint"]
            container.status = "RUNNING"
            container.health_status = "STARTING"
            container.updated_at = datetime.now(timezone.utc)
            dynamodb.update_container(container)

        elif phase in ("Succeeded", "Failed", "Unknown"):
            container.status = "STOPPED"
            container.updated_at = datetime.now(timezone.utc)
            dynamodb.update_container(container)

    except ApiException as exc:
        if exc.status == 404:
            logger.info("k8s pod not found, marking STOPPED: container=%s", container_id)
            container.status = "STOPPED"
            container.updated_at = datetime.now(timezone.utc)
            dynamodb.update_container(container)
        else:
            logger.warning("k8s sync_pod_status API error: container=%s error=%s", container_id, exc)

    return container
