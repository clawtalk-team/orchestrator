#!/usr/bin/env python3
"""
Quick verification script to check AWS configuration before running full tests.

This script verifies:
1. AWS credentials are configured
2. Auth gateway is accessible
3. Orchestrator is accessible
4. DynamoDB table exists and is accessible
5. ECS cluster exists

Run with:
    python scripts/verify_aws_config.py
"""

import json
import os
import sys

import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"

def check(name, fn):
    """Run a check and print result."""
    try:
        print(f"\n{BLUE}Checking: {name}{RESET}")
        result = fn()
        print(f"{GREEN}✓ {name}: OK{RESET}")
        if result:
            print(f"  {result}")
        return True
    except Exception as e:
        print(f"{RED}✗ {name}: FAILED{RESET}")
        print(f"  Error: {e}")
        return False


def check_aws_credentials():
    """Check AWS credentials are configured."""
    import boto3

    profile = os.getenv("AWS_PROFILE", "personal")
    region = os.getenv("AWS_DEFAULT_REGION", "ap-southeast-2")

    try:
        # Try to create a session
        session = boto3.Session(profile_name=profile, region_name=region)
        sts = session.client("sts")
        identity = sts.get_caller_identity()

        return (
            f"Account: {identity['Account']}\n"
            f"  User ARN: {identity['Arn']}\n"
            f"  Profile: {profile}\n"
            f"  Region: {region}"
        )
    except Exception as e:
        raise Exception(f"AWS credentials not configured: {e}")


def check_auth_gateway():
    """Check auth gateway is accessible."""
    url = os.getenv(
        "AUTH_GATEWAY_URL",
        "https://z1fm1cdkph.execute-api.ap-southeast-2.amazonaws.com"
    )

    response = requests.get(f"{url}/health", timeout=10)
    response.raise_for_status()

    return f"URL: {url}"


def check_orchestrator():
    """Check orchestrator is accessible."""
    url = os.getenv(
        "ORCHESTRATOR_URL",
        "https://prz6mum7c7.execute-api.ap-southeast-2.amazonaws.com"
    )

    response = requests.get(f"{url}/health", timeout=10)
    response.raise_for_status()

    return f"URL: {url}"


def check_dynamodb():
    """Check DynamoDB table exists."""
    import boto3

    profile = os.getenv("AWS_PROFILE", "personal")
    region = os.getenv("DYNAMODB_REGION", "ap-southeast-2")
    table_name = os.getenv("CONTAINERS_TABLE", "openclaw-containers")

    session = boto3.Session(profile_name=profile, region_name=region)
    dynamodb = session.client("dynamodb")

    response = dynamodb.describe_table(TableName=table_name)
    table = response["Table"]

    return (
        f"Table: {table_name}\n"
        f"  Status: {table['TableStatus']}\n"
        f"  Region: {region}\n"
        f"  Items: {table.get('ItemCount', 'unknown')}"
    )


def check_ecs_cluster():
    """Check ECS cluster exists."""
    import boto3

    profile = os.getenv("AWS_PROFILE", "personal")
    region = os.getenv("AWS_DEFAULT_REGION", "ap-southeast-2")
    cluster_name = os.getenv("ECS_CLUSTER_NAME", "clawtalk-dev")

    session = boto3.Session(profile_name=profile, region_name=region)
    ecs = session.client("ecs")

    response = ecs.describe_clusters(clusters=[cluster_name])

    if not response["clusters"]:
        raise Exception(f"Cluster '{cluster_name}' not found")

    cluster = response["clusters"][0]

    return (
        f"Cluster: {cluster_name}\n"
        f"  Status: {cluster['status']}\n"
        f"  Running tasks: {cluster.get('runningTasksCount', 0)}\n"
        f"  Pending tasks: {cluster.get('pendingTasksCount', 0)}"
    )


def main():
    """Run all checks."""
    print(f"\n{BLUE}{'=' * 80}{RESET}")
    print(f"{BLUE}AWS Configuration Verification{RESET}")
    print(f"{BLUE}{'=' * 80}{RESET}")

    checks = [
        ("AWS Credentials", check_aws_credentials),
        ("Auth Gateway (Lambda)", check_auth_gateway),
        ("Orchestrator (Lambda)", check_orchestrator),
        ("DynamoDB Table", check_dynamodb),
        ("ECS Cluster", check_ecs_cluster),
    ]

    results = []
    for name, fn in checks:
        results.append(check(name, fn))

    # Summary
    print(f"\n{BLUE}{'=' * 80}{RESET}")
    passed = sum(results)
    total = len(results)

    if passed == total:
        print(f"{GREEN}✓ All checks passed ({passed}/{total}){RESET}")
        print(f"\n{GREEN}Ready to run end-to-end test:{RESET}")
        print(f"  python scripts/test_end_to_end_flow.py")
        sys.exit(0)
    else:
        print(f"{RED}✗ Some checks failed ({passed}/{total} passed){RESET}")
        print(f"\n{YELLOW}Fix the issues above before running tests.{RESET}")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Interrupted by user{RESET}")
        sys.exit(1)
    except Exception as e:
        print(f"\n{RED}Unexpected error: {e}{RESET}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
