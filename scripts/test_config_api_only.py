#!/usr/bin/env python3
"""
Quick smoke test for Config API changes.

Tests only the config creation and retrieval via Config API,
without spinning up containers or AWS resources.
"""

import os
import sys
import time

try:
    from test_end_to_end_flow import (
        AUTH_GATEWAY_URL,
        ORCHESTRATOR_URL,
        make_request,
        print_header,
        print_step,
        print_success,
        print_error,
        print_info,
        GREEN,
        RESET,
    )
except ImportError:
    from scripts.test_end_to_end_flow import (
        AUTH_GATEWAY_URL,
        ORCHESTRATOR_URL,
        make_request,
        print_header,
        print_step,
        print_success,
        print_error,
        print_info,
        GREEN,
        RESET,
    )

def main():
    """Run the config API smoke test."""
    print_header("Config API Smoke Test")

    # Generate unique user email
    timestamp = int(time.time())
    test_email = f"config-test-{timestamp}@example.com"
    test_display_name = f"Config Test {timestamp}"

    try:
        # Step 1: Create User
        print_step(1, "Create test user")
        response = make_request(
            method="POST",
            url=f"{AUTH_GATEWAY_URL}/users",
            json_data={
                "email": test_email,
                "display_name": test_display_name,
            },
            description="Create new user",
        )

        if response.status_code != 201:
            print_error(f"Failed to create user: {response.status_code}")
            sys.exit(1)

        user_data = response.json()
        user_id = user_data["uuid"]
        api_key = user_data["api_key"]
        print_success(f"User created: {user_id}")

        # Step 2: Create Config via API
        print_step(2, "Create config via Config API")

        anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
        if not anthropic_api_key:
            print_error("ANTHROPIC_API_KEY not set")
            sys.exit(1)

        response = make_request(
            method="POST",
            url=f"{ORCHESTRATOR_URL}/config",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json_data={
                "config_name": "default",
                "llm_provider": "anthropic",
                "openclaw_model": "claude-3-5-sonnet-20241022",
                "anthropic_api_key": anthropic_api_key,
                "auth_gateway_api_key": api_key,
            },
            description="Create user config",
        )

        if response.status_code not in (200, 201):
            print_error(f"Failed to create config: {response.status_code}")
            sys.exit(1)

        print_success("Config created via Config API")

        # Step 3: Retrieve Config via API
        print_step(3, "Retrieve config via Config API")

        response = make_request(
            method="GET",
            url=f"{ORCHESTRATOR_URL}/config/default",
            headers={"Authorization": f"Bearer {api_key}"},
            description="Retrieve user config",
        )

        if response.status_code != 200:
            print_error(f"Failed to retrieve config: {response.status_code}")
            sys.exit(1)

        config_data = response.json()
        print_success("Config retrieved via Config API")

        # Verify data
        assert config_data["config_name"] == "default", f"Expected config_name 'default', got {config_data.get('config_name')}"
        assert config_data["llm_provider"] == "anthropic", f"Expected llm_provider 'anthropic', got {config_data.get('llm_provider')}"
        assert config_data["openclaw_model"] == "claude-3-5-sonnet-20241022", f"Expected model 'claude-3-5-sonnet-20241022', got {config_data.get('openclaw_model')}"
        assert "anthropic_api_key" in config_data, "anthropic_api_key missing from response"
        assert "auth_gateway_api_key" in config_data, "auth_gateway_api_key missing from response"
        print_success("Config data validated")

        print(f"\n{GREEN}✓ Config API smoke test passed!{RESET}\n")

    except Exception as e:
        print_error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
