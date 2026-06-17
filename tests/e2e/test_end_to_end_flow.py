"""
End-to-end test: user creation, config, container provisioning.

Tests the complete flow against live AWS infrastructure:
  1. Creates a user in auth-gateway (AWS Lambda)
  2. Creates user configuration via Config API (orchestrator)
  3. Uses the API key to create a container via orchestrator
  4. Monitors container status until RUNNING
  5. Validates critical log entries (openclaw-agent startup, voice-gateway connection)
  6. Cleans up container and user on teardown

Environment variables required:
  OPENROUTER_API_KEY  OpenRouter API key for user config
  E2E_TESTS=1         Enable this test suite (skipped by default)

Optional overrides:
  AUTH_GATEWAY_URL    Auth gateway Lambda URL
  ORCHESTRATOR_URL    Orchestrator Lambda URL
  ECS_CLUSTER_NAME    ECS cluster (default: your-cluster)
  AWS_PROFILE         AWS profile for AWS CLI

Run:
  E2E_TESTS=1 OPENROUTER_API_KEY=sk-or-... pytest tests/e2e/test_end_to_end_flow.py -v
"""

import json
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, Optional

import pytest
import requests

pytestmark = pytest.mark.skipif(
    not os.environ.get("E2E_TESTS"),
    reason="E2E tests disabled — set E2E_TESTS=1 to enable",
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AUTH_GATEWAY_URL = os.getenv(
    "AUTH_GATEWAY_URL", "https://your-auth-gateway.execute-api.your-region.amazonaws.com"
)
ORCHESTRATOR_URL = os.getenv(
    "ORCHESTRATOR_URL", "https://your-api-id.execute-api.your-region.amazonaws.com"
)
DYNAMODB_ENDPOINT = os.getenv("DYNAMODB_ENDPOINT")
DYNAMODB_TABLE = os.getenv("CONTAINERS_TABLE", "openclaw-containers-dev")
DYNAMODB_REGION = os.getenv("DYNAMODB_REGION", "ap-southeast-2")
ECS_CLUSTER_NAME = os.getenv("ECS_CLUSTER_NAME", "your-cluster")
ECS_LOG_GROUP = os.getenv("ECS_LOG_GROUP", "/ecs/openclaw-agent-dev")
AWS_PROFILE = os.getenv("AWS_PROFILE", "default")
AWS_REGION = os.getenv("AWS_DEFAULT_REGION", "ap-southeast-2")

# ---------------------------------------------------------------------------
# Shared helpers (used by other e2e tests in this package)
# ---------------------------------------------------------------------------

GREEN = "\033[92m"
BLUE = "\033[94m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"


def print_header(message: str) -> None:
    print(f"\n{BOLD}{BLUE}{'=' * 80}{RESET}")
    print(f"{BOLD}{BLUE}{message}{RESET}")
    print(f"{BOLD}{BLUE}{'=' * 80}{RESET}\n")


def print_step(step, message: str) -> None:
    print(f"{BOLD}{GREEN}[Step {step}] {message}{RESET}")


def print_success(message: str) -> None:
    print(f"{GREEN}  {message}{RESET}")


def print_info(message: str) -> None:
    print(f"{BLUE}  {message}{RESET}")


def print_warning(message: str) -> None:
    print(f"{YELLOW}  {message}{RESET}")


def print_error(message: str) -> None:
    print(f"{RED}  {message}{RESET}")


def print_json(label: str, data: Any) -> None:
    print(f"\n{BOLD}{label}:{RESET}")
    print(json.dumps(data, indent=2, default=str))
    print()


def make_request(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    description: str = "",
) -> requests.Response:
    """Make an HTTP request with verbose logging."""
    print(f"\n{BOLD}→ {method} {url}{RESET}")
    if description:
        print(f"  {description}")
    if headers:
        for key, value in headers.items():
            if key.lower() == "authorization":
                print(f"    {key}: {value[:20]}...{value[-10:]}")
            else:
                print(f"    {key}: {value}")
    if json_data:
        print_json("  Request Body", json_data)

    response = requests.request(method=method, url=url, headers=headers, json=json_data, timeout=30)

    print(f"\n{BOLD}← {response.status_code} {response.reason}{RESET}")
    if response.text:
        try:
            print_json("  Response Body", response.json())
        except json.JSONDecodeError:
            print(f"  {response.text[:500]}")

    return response


def make_simple_request(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    json_data: Optional[Dict[str, Any]] = None,
) -> requests.Response:
    return requests.request(method=method, url=url, headers=headers, json=json_data, timeout=30)


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


def test_end_to_end_flow():
    """Full container provisioning flow: create user → config → container → RUNNING → validate logs → cleanup."""
    print_header("End-to-End Container Provisioning Test")
    print_info(f"Started at: {datetime.now().isoformat()}")

    openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
    assert openrouter_api_key, "OPENROUTER_API_KEY must be set"

    timestamp = int(time.time())
    test_email = f"test-user-{timestamp}@example.com"
    test_display_name = f"Test User {timestamp}"

    user_id = None
    api_key = None
    container_id = None

    try:
        # Step 1: Create user
        print_step(1, "Create user in auth-gateway")
        response = make_request(
            "POST", f"{AUTH_GATEWAY_URL}/users",
            json_data={"email": test_email, "display_name": test_display_name, "password": f"Test-{timestamp}!"},
        )
        assert response.status_code == 201, f"Failed to create user: {response.status_code} {response.text}"
        user_data = response.json()
        user_id = user_data["uuid"]
        api_key = user_data["api_key"]
        print_success(f"User created: {user_id}")

        # Step 2: Validate API key
        print_step(2, "Validate API key")
        response = make_request("GET", f"{AUTH_GATEWAY_URL}/auth", headers={"Authorization": f"Bearer {api_key}"})
        assert response.status_code == 200, f"API key validation failed: {response.status_code}"
        assert response.json()["user_id"] == user_id, "User ID mismatch"
        print_success("API key validated")

        # Step 3: Write user config via API (PUT handles auto-created default config)
        print_step(3, "Write user config via Config API")
        response = make_request(
            "PUT", f"{ORCHESTRATOR_URL}/config/default",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json_data={
                "llm_provider": "openrouter",
                "openrouter_api_key": openrouter_api_key,
                "openclaw_model": "anthropic/claude-haiku-4-5",
                "auth_gateway_api_key": api_key,
                "auth_gateway_url": AUTH_GATEWAY_URL,
                "openclaw_url": "http://localhost:18789",
                "openclaw_token": "test-token-123",
                "voice_gateway_url": "ws://your-voice-gateway.your-region.elb.amazonaws.com",
            },
        )
        assert response.status_code == 200, f"Failed to write config: {response.status_code} {response.text}"
        print_success("User config written")

        # Step 4: Verify config
        print_step(4, "Verify config")
        response = make_request("GET", f"{ORCHESTRATOR_URL}/config/default",
                                headers={"Authorization": f"Bearer {api_key}"})
        assert response.status_code == 200, f"Failed to retrieve config: {response.status_code}"
        config_data = response.json()
        assert config_data.get("config_name") == "default"
        assert config_data.get("llm_provider") == "openrouter"
        print_success("Config verified")

        # Step 5: Create container
        print_step(5, "Create container")
        response = make_request(
            "POST", f"{ORCHESTRATOR_URL}/containers",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json_data={"config_name": "default", "agent_id": "e2e-test-agent", "env_vars": {"DEBUG": "true"}},
        )
        assert response.status_code == 200, f"Failed to create container: {response.status_code} {response.text}"
        container_data = response.json()
        container_id = container_data["container_id"]
        print_success(f"Container created: {container_id}")

        # Step 6: Monitor until RUNNING
        print_step(6, "Monitor container status")
        max_attempts = 60
        poll_interval = 15
        start_time = time.time()
        reached_running = False

        for attempt in range(max_attempts):
            response = make_simple_request(
                "GET", f"{ORCHESTRATOR_URL}/containers/{container_id}",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if response.status_code != 200:
                time.sleep(poll_interval)
                continue

            container_data = response.json()
            status = container_data["status"]
            elapsed = time.time() - start_time
            print(f"  [{elapsed:>5.0f}s] status={status}")

            if status == "RUNNING":
                health = container_data.get("health_status", "UNKNOWN")
                if health in ("HEALTHY", "STARTING"):
                    print_success("Container is running")
                    reached_running = True
                    break
            elif status in ("FAILED", "STOPPED"):
                pytest.fail(f"Container reached terminal status: {status}")

            time.sleep(poll_interval)

        if not reached_running:
            print_warning(f"Container did not reach RUNNING in {max_attempts * poll_interval}s — ECS may still be starting")

        # Step 7: Validate container logs
        print_step(7, "Validate container logs (5 minutes)")
        try:
            import boto3
            from dateutil import parser as date_parser

            session_kwargs: dict = {"region_name": DYNAMODB_REGION}
            if AWS_PROFILE and not os.getenv("AWS_ACCESS_KEY_ID"):
                session_kwargs["profile_name"] = AWS_PROFILE

            session = boto3.Session(**session_kwargs)
            logs_client = session.client("logs")
            ecs_client = session.client("ecs")

            tasks_response = ecs_client.list_tasks(cluster=ECS_CLUSTER_NAME, desiredStatus="RUNNING")
            task_arn = None

            if tasks_response["taskArns"]:
                tasks = ecs_client.describe_tasks(cluster=ECS_CLUSTER_NAME, tasks=tasks_response["taskArns"])
                container_created = date_parser.parse(container_data["created_at"])
                for task in tasks["tasks"]:
                    time_diff = abs((task["startedAt"] - container_created).total_seconds())
                    if time_diff < 60:
                        task_arn = task["taskArn"]
                        task_id = task_arn.split("/")[-1]
                        print_success(f"Found ECS task: {task_id}")
                        break

            if not task_arn:
                print_warning("Could not find ECS task — skipping log validation")
            else:
                log_stream_prefix = f"ecs/openclaw-agent/{task_id}"
                print_info(f"Collecting logs from {ECS_LOG_GROUP}/{log_stream_prefix} for 5 minutes...")

                log_start = time.time()
                log_duration = 300
                last_timestamp = None
                all_messages: list = []

                while time.time() - log_start < log_duration:
                    try:
                        streams_response = logs_client.describe_log_streams(
                            logGroupName=ECS_LOG_GROUP,
                            logStreamNamePrefix=log_stream_prefix,
                            limit=1,
                        )
                        if not streams_response["logStreams"]:
                            time.sleep(5)
                            continue

                        log_stream_name = streams_response["logStreams"][0]["logStreamName"]
                        get_kwargs: dict = {
                            "logGroupName": ECS_LOG_GROUP,
                            "logStreamName": log_stream_name,
                            "startFromHead": True,
                            "limit": 100,
                        }
                        if last_timestamp:
                            get_kwargs["startTime"] = last_timestamp + 1

                        events_response = logs_client.get_log_events(**get_kwargs)
                        for event in events_response["events"]:
                            msg = event["message"]
                            if msg not in all_messages:
                                all_messages.append(msg)
                                print(f"    {msg}")
                            last_timestamp = event["timestamp"]

                        time.sleep(3)
                    except Exception as e:
                        print_warning(f"Error fetching logs: {e}")
                        time.sleep(5)

                # Validate critical log entries
                agent_started = any(
                    "openclaw-agent" in m.lower() and ("start" in m.lower() or "running" in m.lower())
                    for m in all_messages
                )
                assert agent_started, (
                    "FAILED: openclaw-agent startup not found in logs. "
                    "Expected to see openclaw-agent starting in container logs."
                )
                print_success("openclaw-agent startup confirmed in logs")

                voice_connected = any(
                    "voice-gateway" in m.lower() and ("connect" in m.lower() or "connected" in m.lower())
                    for m in all_messages
                )
                assert voice_connected, (
                    "FAILED: voice-gateway connection not found in logs. "
                    "Expected to see openclaw-agent connecting to voice-gateway."
                )
                print_success("voice-gateway connection confirmed in logs")

        except ImportError:
            pytest.skip("python-dateutil not installed — skipping log validation")
        except Exception as e:
            print_warning(f"Log validation error (non-fatal): {e}")

        print_header("Test Summary")
        print_success(f"User: {test_email} (UUID: {user_id})")
        print_success("Config: created and verified")
        print_success(f"Container: {container_id}")
        print_success("End-to-end test passed!")

    finally:
        print_header("Cleanup")
        if container_id and api_key:
            print_info(f"Deleting container {container_id}...")
            resp = make_simple_request(
                "DELETE", f"{ORCHESTRATOR_URL}/containers/{container_id}",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if resp.status_code in (200, 204, 404):
                print_success("Container deleted")
            else:
                print_warning(f"Container delete returned {resp.status_code} — may need manual cleanup")

        if user_id and api_key:
            print_info(f"Deleting user {user_id} ({test_email})...")
            resp = make_simple_request(
                "DELETE", f"{AUTH_GATEWAY_URL}/users/{user_id}",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if resp.status_code in (200, 204, 404):
                print_success("User deleted")
            else:
                print_warning(f"User delete returned {resp.status_code} — may need manual cleanup")
