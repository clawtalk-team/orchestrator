#!/usr/bin/env python3
"""
Load default configuration into DynamoDB.

This script populates both system-wide defaults and user-specific defaults
into DynamoDB to bootstrap the orchestrator.

Usage:
    # Load system defaults only
    python scripts/load_defaults.py --system

    # Load system defaults + user defaults for a specific user
    python scripts/load_defaults.py --system --user-id test-user-123

    # Load user defaults only (requires existing system config)
    python scripts/load_defaults.py --user-id test-user-123

    # Specify config values
    python scripts/load_defaults.py --system \
        --auth-gateway-url https://example.com \
        --anthropic-key sk-ant-...

    # Verify existing configs
    python scripts/load_defaults.py --verify
"""

import argparse
import sys
from datetime import datetime, timezone
from typing import Optional

import boto3
from botocore.exceptions import ClientError


def get_dynamodb_client(endpoint_url: Optional[str] = None, region: str = "ap-southeast-2"):
    """Get DynamoDB client."""
    if endpoint_url:
        # Local DynamoDB
        return boto3.client(
            "dynamodb",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id="local",
            aws_secret_access_key="local",
        )
    # AWS DynamoDB
    return boto3.client("dynamodb", region_name=region)


def load_system_defaults(
    dynamodb,
    table_name: str,
    auth_gateway_url: str,
    openclaw_url: str,
    openclaw_token: str,
    voice_gateway_url: str = "http://voice-gateway-dev-59337216.ap-southeast-2.elb.amazonaws.com",
):
    """Load system-wide default configuration."""
    print("\n[System Config] Loading system defaults...")

    item = {
        "pk": {"S": "SYSTEM"},
        "sk": {"S": "CONFIG#defaults"},
        "config_type": {"S": "system_config"},
        "auth_gateway_url": {"S": auth_gateway_url},
        "openclaw_url": {"S": openclaw_url},
        "openclaw_token": {"S": openclaw_token},
        "voice_gateway_url": {"S": voice_gateway_url},
        "updated_at": {"S": datetime.now(timezone.utc).isoformat()},
    }

    try:
        dynamodb.put_item(TableName=table_name, Item=item)
        print("✓ System defaults loaded successfully")
        print(f"  auth_gateway_url: {auth_gateway_url}")
        print(f"  openclaw_url: {openclaw_url}")
        print(f"  openclaw_token: {openclaw_token}")
        print(f"  voice_gateway_url: {voice_gateway_url}")
        return True
    except ClientError as e:
        print(f"✗ Failed to load system defaults: {e}")
        return False


def load_user_defaults(
    dynamodb,
    table_name: str,
    user_id: str,
    config_name: str = "default",
    llm_provider: str = "anthropic",
    openclaw_model: str = "claude-3-haiku-20240307",
    auth_gateway_api_key: Optional[str] = None,
    anthropic_api_key: Optional[str] = None,
    openai_api_key: Optional[str] = None,
    openrouter_api_key: Optional[str] = None,
):
    """Load user-specific default configuration."""
    print(f"\n[User Config] Loading user defaults for user_id: {user_id}...")

    item = {
        "pk": {"S": f"USER#{user_id}"},
        "sk": {"S": f"CONFIG#{config_name}"},
        "config_type": {"S": "user_config"},
        "user_id": {"S": user_id},
        "llm_provider": {"S": llm_provider},
        "openclaw_model": {"S": openclaw_model},
        "created_at": {"S": datetime.now(timezone.utc).isoformat()},
        "updated_at": {"S": datetime.now(timezone.utc).isoformat()},
    }

    # Add API keys if provided
    if auth_gateway_api_key:
        item["auth_gateway_api_key"] = {"S": auth_gateway_api_key}
        print(f"  auth_gateway_api_key: {auth_gateway_api_key[:20]}...")

    if anthropic_api_key:
        item["anthropic_api_key"] = {"S": anthropic_api_key}
        print(f"  anthropic_api_key: {anthropic_api_key[:20]}...")

    if openai_api_key:
        item["openai_api_key"] = {"S": openai_api_key}
        print(f"  openai_api_key: {openai_api_key[:20]}...")

    if openrouter_api_key:
        item["openrouter_api_key"] = {"S": openrouter_api_key}
        print(f"  openrouter_api_key: {openrouter_api_key[:20]}...")

    try:
        dynamodb.put_item(TableName=table_name, Item=item)
        print("✓ User defaults loaded successfully")
        print(f"  user_id: {user_id}")
        print(f"  config_name: {config_name}")
        print(f"  llm_provider: {llm_provider}")
        print(f"  openclaw_model: {openclaw_model}")
        return True
    except ClientError as e:
        print(f"✗ Failed to load user defaults: {e}")
        return False


def verify_configs(
    dynamodb,
    table_name: str,
    user_id: Optional[str] = None,
    config_name: str = "default",
):
    """Verify existing configurations."""
    print("\n[Verification] Checking existing configurations...\n")

    # Check system config
    print("System Config (SYSTEM#CONFIG#defaults):")
    try:
        response = dynamodb.get_item(
            TableName=table_name,
            Key={
                "pk": {"S": "SYSTEM"},
                "sk": {"S": "CONFIG#defaults"},
            }
        )

        if "Item" in response:
            print("✓ System config exists")
            item = response["Item"]
            print(f"  auth_gateway_url: {item.get('auth_gateway_url', {}).get('S', 'N/A')}")
            print(f"  openclaw_url: {item.get('openclaw_url', {}).get('S', 'N/A')}")
            print(f"  openclaw_token: {item.get('openclaw_token', {}).get('S', 'N/A')}")
            print(f"  voice_gateway_url: {item.get('voice_gateway_url', {}).get('S', 'N/A')}")
            print(f"  updated_at: {item.get('updated_at', {}).get('S', 'N/A')}")
        else:
            print("✗ System config not found")
    except ClientError as e:
        print(f"✗ Error checking system config: {e}")

    # Check user config if user_id provided
    if user_id:
        print(f"\nUser Config (USER#{user_id}#CONFIG#{config_name}):")
        try:
            response = dynamodb.get_item(
                TableName=table_name,
                Key={
                    "pk": {"S": f"USER#{user_id}"},
                    "sk": {"S": f"CONFIG#{config_name}"},
                }
            )

            if "Item" in response:
                print("✓ User config exists")
                item = response["Item"]
                print(f"  user_id: {item.get('user_id', {}).get('S', 'N/A')}")
                print(f"  llm_provider: {item.get('llm_provider', {}).get('S', 'N/A')}")
                print(f"  openclaw_model: {item.get('openclaw_model', {}).get('S', 'N/A')}")

                # Show masked API keys
                if "auth_gateway_api_key" in item:
                    key = item["auth_gateway_api_key"]["S"]
                    print(f"  auth_gateway_api_key: {key[:20]}..." if len(key) > 20 else f"  auth_gateway_api_key: {key}")

                if "anthropic_api_key" in item:
                    key = item["anthropic_api_key"]["S"]
                    print(f"  anthropic_api_key: {key[:20]}..." if len(key) > 20 else f"  anthropic_api_key: {key}")

                if "openai_api_key" in item:
                    key = item["openai_api_key"]["S"]
                    print(f"  openai_api_key: {key[:20]}..." if len(key) > 20 else f"  openai_api_key: {key}")

                print(f"  created_at: {item.get('created_at', {}).get('S', 'N/A')}")
                print(f"  updated_at: {item.get('updated_at', {}).get('S', 'N/A')}")
            else:
                print("✗ User config not found")
        except ClientError as e:
            print(f"✗ Error checking user config: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Load default configuration into DynamoDB",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Operation mode
    parser.add_argument(
        "--system",
        action="store_true",
        help="Load system defaults"
    )
    parser.add_argument(
        "--user-id",
        help="Load user defaults for specified user_id"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify existing configurations without loading"
    )

    # DynamoDB connection
    parser.add_argument(
        "--endpoint",
        help="DynamoDB endpoint URL (for local development)"
    )
    parser.add_argument(
        "--region",
        default="ap-southeast-2",
        help="AWS region (default: ap-southeast-2)"
    )
    parser.add_argument(
        "--table",
        default="openclaw-containers",
        help="DynamoDB table name (default: openclaw-containers)"
    )

    # System config values
    parser.add_argument(
        "--auth-gateway-url",
        default="https://z1fm1cdkph.execute-api.ap-southeast-2.amazonaws.com",
        help="Auth gateway URL"
    )
    parser.add_argument(
        "--openclaw-url",
        default="http://localhost:18789",
        help="OpenClaw URL"
    )
    parser.add_argument(
        "--openclaw-token",
        default="test-token-123",
        help="OpenClaw token"
    )
    parser.add_argument(
        "--voice-gateway-url",
        default="http://voice-gateway-dev-59337216.ap-southeast-2.elb.amazonaws.com",
        help="Voice gateway URL"
    )

    # User config values
    parser.add_argument(
        "--config-name",
        default="default",
        help="Config name (default: default)"
    )
    parser.add_argument(
        "--llm-provider",
        default="anthropic",
        help="LLM provider (default: anthropic)"
    )
    parser.add_argument(
        "--openclaw-model",
        default="claude-3-haiku-20240307",
        help="OpenClaw model (default: claude-3-haiku-20240307)"
    )
    parser.add_argument(
        "--auth-gateway-api-key",
        help="Auth gateway API key"
    )
    parser.add_argument(
        "--anthropic-api-key",
        help="Anthropic API key"
    )
    parser.add_argument(
        "--openai-api-key",
        help="OpenAI API key"
    )
    parser.add_argument(
        "--openrouter-api-key",
        help="OpenRouter API key"
    )

    args = parser.parse_args()

    # Validate arguments
    if not args.verify and not args.system and not args.user_id:
        print("Error: Must specify --system, --user-id, or --verify")
        parser.print_help()
        sys.exit(1)

    # Connect to DynamoDB
    dynamodb = get_dynamodb_client(args.endpoint, args.region)

    print("=" * 60)
    print("DynamoDB Configuration Loader")
    print("=" * 60)
    print(f"Table: {args.table}")
    print(f"Region: {args.region}")
    if args.endpoint:
        print(f"Endpoint: {args.endpoint}")

    # Verify mode
    if args.verify:
        verify_configs(dynamodb, args.table, args.user_id, args.config_name)
        return

    success = True

    # Load system config
    if args.system:
        success = load_system_defaults(
            dynamodb,
            args.table,
            args.auth_gateway_url,
            args.openclaw_url,
            args.openclaw_token,
            args.voice_gateway_url,
        ) and success

    # Load user config
    if args.user_id:
        success = load_user_defaults(
            dynamodb,
            args.table,
            args.user_id,
            args.config_name,
            args.llm_provider,
            args.openclaw_model,
            args.auth_gateway_api_key,
            args.anthropic_api_key,
            args.openai_api_key,
            args.openrouter_api_key,
        ) and success

    # Verify what was loaded
    print("\n" + "=" * 60)
    verify_configs(dynamodb, args.table, args.user_id, args.config_name)

    print("\n" + "=" * 60)
    if success:
        print("✓ Configuration loaded successfully!")
    else:
        print("✗ Some configurations failed to load")
        sys.exit(1)

    print("=" * 60)


if __name__ == "__main__":
    main()
