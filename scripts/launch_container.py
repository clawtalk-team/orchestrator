#!/usr/bin/env python3
"""
Launch a new openclaw-agent container.
Creates a container via the orchestrator API and optionally waits for it to become healthy.

Usage:
  # Launch with defaults
  python scripts/launch_container.py --user-id USER_123 --token YOUR_TOKEN

  # Launch with custom name and config
  python scripts/launch_container.py --user-id USER_123 --token YOUR_TOKEN \\
    --name my-agent --config '{"memory": 512}'

  # Launch and wait for health check
  python scripts/launch_container.py --user-id USER_123 --token YOUR_TOKEN --wait

  # Use local development environment
  python scripts/launch_container.py --user-id USER_123 --token YOUR_TOKEN --local
"""

import argparse
import json
import sys
import time
from typing import Optional

import requests


def launch_container(
    user_id: str,
    token: str,
    base_url: str,
    name: Optional[str] = None,
    config: Optional[dict] = None,
    wait: bool = False,
    wait_timeout: int = 300,
) -> dict:
    """Launch a new container via the orchestrator API."""

    # Build authorization header
    auth_token = f"{user_id}:{token}"
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
    }

    # Build request body
    body = {}
    if name:
        body["name"] = name
    if config:
        body["config"] = config

    print(f"==> Launching container via {base_url}/containers")
    if name:
        print(f"    Name: {name}")
    if config:
        print(f"    Config: {json.dumps(config, indent=2)}")
    print()

    # Create container
    try:
        response = requests.post(
            f"{base_url}/containers", headers=headers, json=body, timeout=30
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"✗ Error creating container: {e}")
        if hasattr(e, "response") and e.response is not None:
            print(f"Response: {e.response.text}")
        sys.exit(1)

    container = response.json()

    print(f"✓ Container created successfully!")
    print(f"\n{'='*60}")
    print(f"Container ID:    {container['container_id']}")
    print(f"Status:          {container['status']}")
    print(f"Health Status:   {container['health_status']}")
    print(f"IP Address:      {container.get('ip_address', 'Not yet assigned')}")
    print(f"Created At:      {container['created_at']}")
    print(f"{'='*60}\n")

    # Wait for container to become healthy if requested
    if wait:
        print(f"Waiting for container to become healthy (timeout: {wait_timeout}s)...")
        container_id = container["container_id"]
        start_time = time.time()

        while time.time() - start_time < wait_timeout:
            try:
                health_response = requests.get(
                    f"{base_url}/containers/{container_id}/health",
                    headers=headers,
                    timeout=10,
                )
                health_response.raise_for_status()
                health = health_response.json()

                health_status = health["health_status"]
                print(f"  Status: {health_status}", end="\r")

                if health_status == "HEALTHY":
                    print(f"\n\n✓ Container is now HEALTHY!")
                    if health.get("health_data"):
                        data = health["health_data"]
                        print(f"  Agents running: {data.get('agents_running', 0)}")
                        print(f"  Uptime: {data.get('uptime_seconds', 0)}s")
                        print(f"  Memory: {data.get('memory_mb', 0)}MB")
                        print(f"  CPU: {data.get('cpu_percent', 0):.1f}%")
                    break
                elif health_status in ["UNHEALTHY", "FAILED"]:
                    print(f"\n\n✗ Container is {health_status}")
                    sys.exit(1)

                time.sleep(5)

            except requests.exceptions.RequestException as e:
                print(f"\n✗ Error checking health: {e}")
                break
        else:
            print(f"\n\n⚠ Timeout waiting for container to become healthy")
            print(f"Container may still be starting. Check status with:")
            print(f"  python scripts/list_containers.py --user-id {user_id}")

    return container


def main():
    parser = argparse.ArgumentParser(
        description="Launch a new openclaw-agent container",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Launch with defaults
  %(prog)s --user-id USER_123 --token YOUR_TOKEN

  # Launch with custom name
  %(prog)s --user-id USER_123 --token YOUR_TOKEN --name my-agent

  # Launch with config
  %(prog)s --user-id USER_123 --token YOUR_TOKEN --config '{"memory": 512}'

  # Launch and wait for health
  %(prog)s --user-id USER_123 --token YOUR_TOKEN --wait

  # Use local environment
  %(prog)s --user-id USER_123 --token YOUR_TOKEN --local
        """,
    )

    parser.add_argument("--user-id", required=True, help="User ID (for authentication)")
    parser.add_argument("--token", required=True, help="Authentication token")
    parser.add_argument("--name", help="Optional container name")
    parser.add_argument("--config", help="Optional config as JSON string")
    parser.add_argument("--env", default="dev", help="Environment (dev/prod)")
    parser.add_argument(
        "--local",
        action="store_true",
        help="Use local development URL (localhost:8000)",
    )
    parser.add_argument("--url", help="Custom base URL (overrides --env and --local)")
    parser.add_argument(
        "--wait", action="store_true", help="Wait for container to become healthy"
    )
    parser.add_argument(
        "--wait-timeout",
        type=int,
        default=300,
        help="Health check timeout in seconds (default: 300)",
    )

    args = parser.parse_args()

    # Determine base URL
    if args.url:
        base_url = args.url.rstrip("/")
    elif args.local:
        base_url = "http://localhost:8000"
    else:
        # Production URLs by environment
        urls = {
            "dev": "https://prz6mum7c7.execute-api.ap-southeast-2.amazonaws.com",
            "prod": "https://api.openclaw.ai",  # placeholder
        }
        base_url = urls.get(args.env, urls["dev"])

    # Parse config if provided
    config = None
    if args.config:
        try:
            config = json.loads(args.config)
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in --config: {e}")
            sys.exit(1)

    # Launch container
    container = launch_container(
        user_id=args.user_id,
        token=args.token,
        base_url=base_url,
        name=args.name,
        config=config,
        wait=args.wait,
        wait_timeout=args.wait_timeout,
    )

    print(f"\n==> Next steps:")
    print(f"  # View logs")
    print(
        f"  python scripts/get_logs.py {container['container_id']} --user-id {args.user_id}"
    )
    print(f"\n  # Get shell")
    print(
        f"  python scripts/exec_shell.py {container['container_id']} --user-id {args.user_id}"
    )
    print(f"\n  # Delete container")
    print(
        f"  python scripts/delete_containers.py {container['container_id']} --user-id {args.user_id}"
    )


if __name__ == "__main__":
    main()
