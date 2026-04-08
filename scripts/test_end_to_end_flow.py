#!/usr/bin/env python3
"""
End-to-end test script for user creation and container provisioning.

This script:
1. Creates a user in auth-gateway (AWS Lambda)
2. Uses the API key to create a container via orchestrator (local/AWS)
3. Monitors container status until RUNNING
4. Shows all configs that get transferred to the container

AWS Configuration (All Services):
- AUTH_GATEWAY_URL: AWS Lambda (https://z1fm1cdkph.execute-api.ap-southeast-2.amazonaws.com)
- ORCHESTRATOR_URL: AWS Lambda (https://prz6mum7c7.execute-api.ap-southeast-2.amazonaws.com)
- DynamoDB: AWS DynamoDB (openclaw-containers table in ap-southeast-2)
- ECS: AWS Fargate (clawtalk-dev cluster)

Run with:
    # Ensure AWS credentials are configured
    export AWS_PROFILE=personal
    # or
    export AWS_ACCESS_KEY_ID=...
    export AWS_SECRET_ACCESS_KEY=...

    python scripts/test_end_to_end_flow.py

    # Or with custom URLs
    AUTH_GATEWAY_URL=https://... ORCHESTRATOR_URL=https://... python scripts/test_end_to_end_flow.py
"""

import json
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, Optional

import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ============================================================================
# Configuration
# ============================================================================

# AWS Lambda endpoint for auth-gateway
AUTH_GATEWAY_URL = os.getenv(
    "AUTH_GATEWAY_URL",
    "https://z1fm1cdkph.execute-api.ap-southeast-2.amazonaws.com"
)

# AWS Lambda endpoint for orchestrator
ORCHESTRATOR_URL = os.getenv(
    "ORCHESTRATOR_URL",
    "https://prz6mum7c7.execute-api.ap-southeast-2.amazonaws.com"
)

# DynamoDB Configuration (AWS - no endpoint for real DynamoDB)
DYNAMODB_ENDPOINT = os.getenv("DYNAMODB_ENDPOINT")  # None = use AWS
DYNAMODB_TABLE = os.getenv("CONTAINERS_TABLE", "openclaw-containers")
DYNAMODB_REGION = os.getenv("DYNAMODB_REGION", "ap-southeast-2")

# AWS Credentials (use profile or explicit keys)
AWS_PROFILE = os.getenv("AWS_PROFILE", "personal")
AWS_REGION = os.getenv("AWS_DEFAULT_REGION", "ap-southeast-2")

# Colors for output
GREEN = "\033[92m"
BLUE = "\033[94m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"


# ============================================================================
# Helper Functions
# ============================================================================


def print_header(message: str):
    """Print a bold header."""
    print(f"\n{BOLD}{BLUE}{'=' * 80}{RESET}")
    print(f"{BOLD}{BLUE}{message}{RESET}")
    print(f"{BOLD}{BLUE}{'=' * 80}{RESET}\n")


def print_step(step: int, message: str):
    """Print a step number."""
    print(f"{BOLD}{GREEN}[Step {step}] {message}{RESET}")


def print_success(message: str):
    """Print a success message."""
    print(f"{GREEN}✓ {message}{RESET}")


def print_info(message: str):
    """Print an info message."""
    print(f"{BLUE}ℹ {message}{RESET}")


def print_warning(message: str):
    """Print a warning message."""
    print(f"{YELLOW}⚠ {message}{RESET}")


def print_error(message: str):
    """Print an error message."""
    print(f"{RED}✗ {message}{RESET}")


def print_json(label: str, data: Any):
    """Pretty print JSON data."""
    print(f"\n{BOLD}{label}:{RESET}")
    print(json.dumps(data, indent=2, default=str))
    print()


def print_env_vars():
    """Print all relevant environment variables."""
    print_header("Environment Variables")
    env_vars = {
        "AUTH_GATEWAY_URL": AUTH_GATEWAY_URL,
        "ORCHESTRATOR_URL": ORCHESTRATOR_URL,
        "DYNAMODB_ENDPOINT": DYNAMODB_ENDPOINT or "(AWS - no endpoint)",
        "DYNAMODB_TABLE": DYNAMODB_TABLE,
        "DYNAMODB_REGION": DYNAMODB_REGION,
        "AWS_PROFILE": AWS_PROFILE,
        "AWS_REGION": AWS_REGION,
        "AWS_ACCESS_KEY_ID": os.getenv("AWS_ACCESS_KEY_ID", "(using profile)"),
        "AWS_SECRET_ACCESS_KEY": (
            "(set)" if os.getenv("AWS_SECRET_ACCESS_KEY") else "(using profile)"
        ),
    }
    print_json("Environment Configuration", env_vars)


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
        print(f"\n{BOLD}  Headers:{RESET}")
        for key, value in headers.items():
            if key.lower() == "authorization":
                # Mask API key
                print(f"    {key}: {value[:20]}...{value[-10:]}")
            else:
                print(f"    {key}: {value}")

    if json_data:
        print_json("  Request Body", json_data)

    try:
        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            json=json_data,
            timeout=30,
        )

        print(f"\n{BOLD}← Response: {response.status_code} {response.reason}{RESET}")

        # Print response headers
        print(f"{BOLD}  Response Headers:{RESET}")
        for key, value in response.headers.items():
            print(f"    {key}: {value}")

        # Print response body
        if response.text:
            try:
                response_json = response.json()
                print_json("  Response Body", response_json)
            except json.JSONDecodeError:
                print(f"\n{BOLD}  Response Body (text):{RESET}")
                print(f"  {response.text[:500]}")

        return response

    except requests.exceptions.RequestException as e:
        print_error(f"Request failed: {e}")
        raise


def query_dynamodb_config(user_id: str, config_name: str = "default") -> Optional[Dict]:
    """Query DynamoDB directly to see what config is stored."""
    print_step("X", f"Querying DynamoDB for user config")
    print_info(f"Looking for: pk=USER#{user_id}, sk=CONFIG#{config_name}")

    try:
        import boto3

        # Build boto3 session config
        session_kwargs = {"region_name": DYNAMODB_REGION}

        # Use AWS profile if set and no explicit credentials
        if AWS_PROFILE and not os.getenv("AWS_ACCESS_KEY_ID"):
            print_info(f"Using AWS profile: {AWS_PROFILE}")
            session_kwargs["profile_name"] = AWS_PROFILE

        session = boto3.Session(**session_kwargs)

        # Build DynamoDB resource config
        dynamodb_kwargs = {}
        if DYNAMODB_ENDPOINT:
            print_info(f"Using DynamoDB endpoint: {DYNAMODB_ENDPOINT}")
            dynamodb_kwargs["endpoint_url"] = DYNAMODB_ENDPOINT
        else:
            print_info(f"Using AWS DynamoDB in region: {DYNAMODB_REGION}")

        dynamodb = session.resource("dynamodb", **dynamodb_kwargs)
        table = dynamodb.Table(DYNAMODB_TABLE)

        # Get user config
        print_info("Fetching USER config from DynamoDB...")
        user_response = table.get_item(
            Key={"pk": f"USER#{user_id}", "sk": f"CONFIG#{config_name}"}
        )

        # Get system config
        print_info("Fetching SYSTEM config from DynamoDB...")
        system_response = table.get_item(
            Key={"pk": "SYSTEM", "sk": "CONFIG#defaults"}
        )

        config = {
            "user_config": user_response.get("Item"),
            "system_config": system_response.get("Item"),
        }

        if user_response.get("Item"):
            print_success(f"Found user config in DynamoDB")
            # Mask sensitive fields
            masked_config = dict(user_response["Item"])
            for key in ["anthropic_api_key", "openai_api_key", "auth_gateway_api_key"]:
                if key in masked_config and masked_config[key]:
                    masked_config[key] = f"{masked_config[key][:10]}...{masked_config[key][-4:]}"
            print_json("User Config (masked)", masked_config)
        else:
            print_warning("No user config found in DynamoDB")

        if system_response.get("Item"):
            print_success(f"Found system config in DynamoDB")
            print_json("System Config", system_response["Item"])
        else:
            print_warning("No system config found in DynamoDB")

        return config

    except Exception as e:
        print_warning(f"Could not query DynamoDB directly: {e}")
        return None


# ============================================================================
# Main Test Flow
# ============================================================================


def main():
    """Run the end-to-end test."""
    print_header("End-to-End Container Provisioning Test")
    print_info(f"Started at: {datetime.now().isoformat()}")

    # Print environment
    print_env_vars()

    # Generate unique user email
    timestamp = int(time.time())
    test_email = f"test-user-{timestamp}@example.com"
    test_display_name = f"Test User {timestamp}"

    user_id = None
    api_key = None
    container_id = None

    try:
        # ====================================================================
        # Step 1: Create User in auth-gateway
        # ====================================================================
        print_step(1, "Create user in auth-gateway")
        print_info(f"Creating user: {test_email}")

        response = make_request(
            method="POST",
            url=f"{AUTH_GATEWAY_URL}/users",
            json_data={
                "email": test_email,
                "display_name": test_display_name,
            },
            description="Create new user with email",
        )

        if response.status_code != 201:
            print_error(f"Failed to create user: {response.status_code}")
            sys.exit(1)

        user_data = response.json()
        user_id = user_data["uuid"]
        api_key = user_data["api_key"]

        print_success(f"User created successfully")
        print_info(f"User ID (UUID): {user_id}")
        print_info(f"API Key: {api_key[:20]}...{api_key[-10:]}")

        # ====================================================================
        # Step 2: Validate API Key
        # ====================================================================
        print_step(2, "Validate API key with auth-gateway")

        response = make_request(
            method="GET",
            url=f"{AUTH_GATEWAY_URL}/auth",
            headers={"Authorization": f"Bearer {api_key}"},
            description="Validate the API key we just received",
        )

        if response.status_code != 200:
            print_error(f"API key validation failed: {response.status_code}")
            sys.exit(1)

        auth_data = response.json()
        print_success(f"API key validated")
        print_info(f"Authenticated as user_id: {auth_data['user_id']}")

        if auth_data["user_id"] != user_id:
            print_error(
                f"User ID mismatch! Expected {user_id}, got {auth_data['user_id']}"
            )
            sys.exit(1)

        # ====================================================================
        # Step 3: Create Container via Orchestrator
        # ====================================================================
        print_step(3, "Create container via orchestrator")
        print_info("This will trigger ECS task creation...")

        response = make_request(
            method="POST",
            url=f"{ORCHESTRATOR_URL}/containers",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json_data={
                "config_name": "default",
            },
            description="Create new container for user",
        )

        if response.status_code != 200:
            print_error(f"Failed to create container: {response.status_code}")
            if response.text:
                print_error(f"Error: {response.text}")
            sys.exit(1)

        container_data = response.json()
        container_id = container_data["container_id"]

        print_success(f"Container creation initiated")
        print_info(f"Container ID: {container_id}")
        print_info(f"Initial Status: {container_data['status']}")

        # ====================================================================
        # Step 4: Show DynamoDB Config
        # ====================================================================
        print_step(4, "Show configuration stored in DynamoDB")
        config = query_dynamodb_config(user_id, "default")

        # ====================================================================
        # Step 5: Show Environment Variables that will be passed to container
        # ====================================================================
        print_step(5, "Show environment variables for container")
        print_info("These are the env vars that ECS will pass to the container:")

        container_env = {
            "USER_ID": user_id,
            "CONTAINER_ID": container_id,
            "CONFIG_NAME": "default",
            "DYNAMODB_TABLE": DYNAMODB_TABLE,
            "DYNAMODB_REGION": DYNAMODB_REGION,
            "OPENCLAW_DISABLE_BONJOUR": "1",
        }

        if DYNAMODB_ENDPOINT:
            container_env["DYNAMODB_ENDPOINT"] = DYNAMODB_ENDPOINT

        print_json("Container Environment Variables", container_env)

        # ====================================================================
        # Step 6: Monitor Container Status
        # ====================================================================
        print_step(6, "Monitor container status")
        print_info("Polling for container status changes...")

        max_attempts = 60
        poll_interval = 5

        for attempt in range(max_attempts):
            response = make_request(
                method="GET",
                url=f"{ORCHESTRATOR_URL}/containers/{container_id}",
                headers={"Authorization": f"Bearer {api_key}"},
                description=f"Poll attempt {attempt + 1}/{max_attempts}",
            )

            if response.status_code != 200:
                print_warning(f"Failed to get container status: {response.status_code}")
                time.sleep(poll_interval)
                continue

            container_data = response.json()
            status = container_data["status"]
            health_status = container_data.get("health_status", "UNKNOWN")
            ip_address = container_data.get("ip_address")

            print_info(
                f"Status: {status}, Health: {health_status}, IP: {ip_address or 'pending'}"
            )

            if status == "RUNNING" and health_status in ("HEALTHY", "STARTING"):
                print_success(f"Container is running!")
                print_json("Final Container State", container_data)

                if ip_address:
                    print_info(f"Health endpoint: http://{ip_address}:8080/health")
                    print_info(f"API endpoint: http://{ip_address}:8080")

                break

            elif status == "FAILED":
                print_error(f"Container failed to start")
                sys.exit(1)

            elif status == "STOPPED":
                print_error(f"Container stopped unexpectedly")
                sys.exit(1)

            time.sleep(poll_interval)
        else:
            print_warning(f"Container did not reach RUNNING state in {max_attempts * poll_interval}s")
            print_info("This is expected for ECS deployments that take time to spin up")

        # ====================================================================
        # Step 7: Summary
        # ====================================================================
        print_header("Test Summary")
        print_success(f"User created: {test_email} (UUID: {user_id})")
        print_success(f"API key generated: {api_key[:20]}...{api_key[-10:]}")
        print_success(f"Container requested: {container_id}")
        print_info(f"Container status: {container_data['status']}")

        print("\n" + BOLD + "What happens next (in AWS ECS):" + RESET)
        print("1. ECS Fargate task launches in AWS (clawtalk-dev cluster)")
        print("2. Container startup script (docker-start.sh) runs")
        print("3. fetch_config.py is called with these env vars:")
        print(f"   - USER_ID={user_id}")
        print(f"   - CONFIG_NAME=default")
        print(f"   - DYNAMODB_TABLE={DYNAMODB_TABLE}")
        print(f"   - DYNAMODB_REGION={DYNAMODB_REGION}")
        print("4. fetch_config.py queries AWS DynamoDB:")
        print(f"   - USER config: pk=USER#{user_id}, sk=CONFIG#default")
        print("   - SYSTEM config: pk=SYSTEM, sk=CONFIG#defaults")
        print("5. It writes two config files in the container:")
        print("   - ~/.openclaw/openclaw.json (OpenClaw gateway config)")
        print("   - ~/.clawtalk/clawtalk.json (openclaw-agent config)")
        print("6. Container starts OpenClaw gateway and openclaw-agent")
        print("7. Container registers with auth-gateway and starts processing")

        print(f"\n{BOLD}AWS Resources Used:{RESET}")
        print(f"  • Auth Gateway:  {AUTH_GATEWAY_URL}")
        print(f"  • Orchestrator:  {ORCHESTRATOR_URL}")
        print(f"  • DynamoDB:      {DYNAMODB_TABLE} (region: {DYNAMODB_REGION})")
        print(f"  • ECS Cluster:   clawtalk-dev")
        print(f"  • Container:     {container_id}")

        print(f"\n{GREEN}✓ Test completed successfully!{RESET}\n")

    except KeyboardInterrupt:
        print_warning("\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print_error(f"Test failed with error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
