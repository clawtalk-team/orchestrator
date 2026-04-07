#!/usr/bin/env python3
"""
Setup test configuration in DynamoDB for testing container config delivery.

This script creates:
1. System config (SYSTEM#CONFIG#defaults) - URLs, tokens
2. User config (USER#{user_id}#CONFIG#primary) - API keys, settings

Usage:
    python scripts/setup_test_config.py --user-id test-user-123 --anthropic-key sk-ant-...
"""

import argparse
import sys
from datetime import datetime

import boto3


def setup_test_config(
    user_id: str,
    anthropic_key: str = "",
    openai_key: str = "",
    openrouter_key: str = "",
    endpoint_url: str = "http://localhost:8000",
    region: str = "ap-southeast-2",
    table_name: str = "openclaw-containers",
):
    """
    Create test configuration in DynamoDB.

    Args:
        user_id: The user ID to create config for
        anthropic_key: Anthropic API key
        openai_key: OpenAI API key
        openrouter_key: OpenRouter API key
        endpoint_url: DynamoDB endpoint
        region: AWS region
        table_name: DynamoDB table name
    """
    # Connect to DynamoDB
    dynamodb = boto3.resource(
        "dynamodb",
        endpoint_url=endpoint_url,
        region_name=region,
        aws_access_key_id="local",
        aws_secret_access_key="local",
    )

    table = dynamodb.Table(table_name)

    print(f"Setting up test config in DynamoDB table: {table_name}")
    print(f"Endpoint: {endpoint_url}")
    print(f"User ID: {user_id}")
    print()

    # Determine LLM provider based on which key is provided
    llm_provider = "anthropic"
    if openrouter_key:
        llm_provider = "openrouter"
    elif openai_key:
        llm_provider = "openai"

    # Create system config
    print("[1/2] Creating system config...")
    system_config = {
        "pk": "SYSTEM",
        "sk": "CONFIG#defaults",
        "config_type": "system_config",
        "auth_gateway_url": "http://host.docker.internal:8001",
        "openclaw_url": "http://localhost:18789",
        "openclaw_token": "test-token-123",
        "voice_gateway_url": "ws://localhost:9090",
        "updated_at": datetime.utcnow().isoformat(),
    }

    table.put_item(Item=system_config)
    print("✓ System config created")
    print(f"  auth_gateway_url: {system_config['auth_gateway_url']}")
    print(f"  openclaw_url: {system_config['openclaw_url']}")
    print()

    # Create user config
    print("[2/2] Creating user config...")
    user_config = {
        "pk": f"USER#{user_id}",
        "sk": "CONFIG#primary",
        "config_type": "user_config",
        "user_id": user_id,
        "llm_provider": llm_provider,
        "openclaw_model": "claude-3-haiku-20240307",
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }

    # Add API keys (not encrypted for testing)
    # In production, these would be encrypted
    if anthropic_key:
        user_config["anthropic_api_key"] = anthropic_key
        print(f"  anthropic_api_key: {anthropic_key[:20]}...")

    if openai_key:
        user_config["openai_api_key"] = openai_key
        print(f"  openai_api_key: {openai_key[:20]}...")

    if openrouter_key:
        user_config["openrouter_api_key"] = openrouter_key
        print(f"  openrouter_api_key: {openrouter_key[:20]}...")

    # Add auth gateway API key (format: user_id:token)
    auth_api_key = f"{user_id}:test-token-xyz-789"
    user_config["auth_gateway_api_key"] = auth_api_key
    print(f"  auth_gateway_api_key: {auth_api_key}")

    table.put_item(Item=user_config)
    print("✓ User config created")
    print(f"  user_id: {user_id}")
    print(f"  llm_provider: {llm_provider}")
    print()

    print("=== Test config setup complete ===")
    print()
    print("Next steps:")
    print(f"  1. Test fetch_config.py:")
    print(f"     python scripts/container/fetch_config.py --user-id {user_id}")
    print()
    print(f"  2. Create container via API:")
    print(f"     curl -X POST http://localhost:8000/containers \\")
    print(f"       -H 'Authorization: Bearer {auth_api_key}' \\")
    print(f"       -H 'Content-Type: application/json'")
    print()
    print(f"  3. View config in DynamoDB:")
    print(f"     aws dynamodb get-item \\")
    print(f"       --table-name {table_name} \\")
    print(
        f'       --key \'{{"pk":{{"S":"USER#{user_id}"}},"sk":{{"S":"CONFIG#primary"}}}}\' \\'
    )
    print(f"       --endpoint-url {endpoint_url} \\")
    print(f"       --region {region}")


def main():
    parser = argparse.ArgumentParser(description="Setup test configuration in DynamoDB")
    parser.add_argument(
        "--user-id", required=True, help="User ID (e.g., test-user-123)"
    )
    parser.add_argument("--anthropic-key", help="Anthropic API key")
    parser.add_argument("--openai-key", help="OpenAI API key")
    parser.add_argument("--openrouter-key", help="OpenRouter API key")
    parser.add_argument(
        "--endpoint",
        default="http://localhost:8000",
        help="DynamoDB endpoint (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--region",
        default="ap-southeast-2",
        help="AWS region (default: ap-southeast-2)",
    )
    parser.add_argument(
        "--table",
        default="openclaw-containers",
        help="DynamoDB table name (default: openclaw-containers)",
    )

    args = parser.parse_args()

    # Require at least one API key
    if not any([args.anthropic_key, args.openai_key, args.openrouter_key]):
        print("ERROR: At least one API key is required")
        print("  --anthropic-key, --openai-key, or --openrouter-key")
        sys.exit(1)

    setup_test_config(
        user_id=args.user_id,
        anthropic_key=args.anthropic_key or "",
        openai_key=args.openai_key or "",
        openrouter_key=args.openrouter_key or "",
        endpoint_url=args.endpoint,
        region=args.region,
        table_name=args.table,
    )


if __name__ == "__main__":
    main()
