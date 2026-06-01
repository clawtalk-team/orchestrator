"""
E2E smoke test for the Config API.

Tests config creation and retrieval without spinning up containers or ECS tasks.
Requires live AWS endpoints and auth-gateway.

Environment variables required:
  OPENROUTER_API_KEY  OpenRouter API key
  E2E_TESTS=1         Enable this test suite (skipped by default)

Run:
  E2E_TESTS=1 OPENROUTER_API_KEY=sk-or-... pytest tests/e2e/test_config_api.py -v
"""

import os
import time

import pytest

from tests.e2e.test_end_to_end_flow import (
    AUTH_GATEWAY_URL,
    ORCHESTRATOR_URL,
    make_request,
    make_simple_request,
    print_header,
    print_step,
    print_success,
    print_error,
    print_info,
    print_warning,
    GREEN,
    RESET,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("E2E_TESTS"),
    reason="E2E tests disabled — set E2E_TESTS=1 to enable",
)


def test_config_api_smoke():
    """Create and retrieve config via the Config API without launching a container."""
    print_header("Config API Smoke Test")

    openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
    assert openrouter_api_key, "OPENROUTER_API_KEY must be set"

    timestamp = int(time.time())
    test_email = f"config-test-{timestamp}@example.com"
    test_display_name = f"Config Test {timestamp}"

    user_id = None
    api_key = None

    try:
        # Step 1: Create test user
        print_step(1, "Create test user")
        response = make_request(
            "POST", f"{AUTH_GATEWAY_URL}/users",
            json_data={"email": test_email, "display_name": test_display_name, "password": f"Test-{timestamp}!"},
        )
        assert response.status_code == 201, f"Failed to create user: {response.status_code} {response.text}"
        user_data = response.json()
        user_id = user_data["uuid"]
        api_key = user_data["api_key"]
        print_success(f"User created: {user_id}")

        # Step 2: Write config via API (PUT to handle auto-created default config)
        print_step(2, "Write config via Config API")
        response = make_request(
            "PUT", f"{ORCHESTRATOR_URL}/config/default",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json_data={
                "llm_provider": "openrouter",
                "openclaw_model": "anthropic/claude-haiku-4-5",
                "openrouter_api_key": openrouter_api_key,
                "auth_gateway_api_key": api_key,
            },
        )
        assert response.status_code == 200, f"Failed to write config: {response.status_code} {response.text}"
        print_success("Config written")

        # Step 3: Retrieve config via API
        print_step(3, "Retrieve config via Config API")
        response = make_request(
            "GET", f"{ORCHESTRATOR_URL}/config/default",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert response.status_code == 200, f"Failed to retrieve config: {response.status_code} {response.text}"

        config_data = response.json()
        assert config_data["config_name"] == "default", \
            f"Expected config_name 'default', got {config_data.get('config_name')}"
        assert config_data["llm_provider"] == "openrouter", \
            f"Expected llm_provider 'openrouter', got {config_data.get('llm_provider')}"
        assert config_data["openclaw_model"] == "anthropic/claude-haiku-4-5", \
            f"Expected model 'anthropic/claude-haiku-4-5', got {config_data.get('openclaw_model')}"
        assert config_data.get("openrouter_api_key"), "openrouter_api_key missing or empty in response"
        assert config_data.get("auth_gateway_api_key"), "auth_gateway_api_key missing or empty in response"

        print_success("Config data validated")
        print(f"\n{GREEN}Config API smoke test passed!{RESET}\n")

    finally:
        print_header("Cleanup")
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
