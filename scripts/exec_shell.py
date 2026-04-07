#!/usr/bin/env python3
"""
Get an interactive shell on an openclaw-agent container.
Uses ECS exec to connect to a running task.

Usage:
  python scripts/exec_shell.py CONTAINER_ID --user-id USER_ID [--env ENV]
  python scripts/exec_shell.py --task-arn TASK_ARN [--env ENV]

Prerequisites:
  - ECS exec must be enabled on the task (enableExecuteCommand: true)
  - Session Manager plugin must be installed:
    https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html
"""

import argparse
import subprocess
import sys

import boto3


def get_task_arn(
    container_id: str, user_id: str, env: str, profile: str, region: str
) -> str:
    """Look up task ARN from DynamoDB."""
    table_name = f"openclaw-containers-{env}"

    session = boto3.Session(profile_name=profile, region_name=region)
    dynamodb = session.client("dynamodb")

    print(f"==> Looking up task ARN for container {container_id}...")

    response = dynamodb.get_item(
        TableName=table_name,
        Key={"pk": {"S": f"USER#{user_id}"}, "sk": {"S": f"CONTAINER#{container_id}"}},
    )

    item = response.get("Item")
    if not item or "task_arn" not in item:
        print(f"Error: Could not find task ARN for container {container_id}")
        sys.exit(1)

    task_arn = item["task_arn"]["S"]
    if not task_arn or task_arn == "None":
        print(f"Error: No task ARN set for container {container_id}")
        sys.exit(1)

    return task_arn


def exec_shell(
    task_arn: str,
    cluster: str,
    container_name: str,
    profile: str,
    region: str,
    command: str = "/bin/bash",
):
    """Execute interactive shell on ECS task."""
    task_id = task_arn.split("/")[-1]

    print(f"==> Connecting to task: {task_id}")
    print(f"    Cluster: {cluster}")
    print(f"    Container: {container_name}")
    print()

    # Build AWS CLI command
    cmd = [
        "aws",
        "ecs",
        "execute-command",
        "--profile",
        profile,
        "--region",
        region,
        "--cluster",
        cluster,
        "--task",
        task_id,
        "--container",
        container_name,
        "--interactive",
        "--command",
        command,
    ]

    try:
        # Execute the command and let it take over the terminal
        result = subprocess.run(cmd)
        sys.exit(result.returncode)
    except FileNotFoundError:
        print("Error: AWS CLI not found. Please install the AWS CLI.")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n==> Session interrupted")
        sys.exit(0)


def main():
    parser = argparse.ArgumentParser(
        description="Get shell on openclaw-agent container"
    )
    parser.add_argument(
        "container_id", nargs="?", help="Container ID (e.g., oc-abc12345)"
    )
    parser.add_argument("--user-id", help="User ID who owns the container")
    parser.add_argument(
        "--task-arn", help="Task ARN to connect to (alternative to container-id)"
    )
    parser.add_argument("--env", default="dev", help="Environment (dev/prod)")
    parser.add_argument("--profile", default="personal", help="AWS profile name")
    parser.add_argument("--region", default="ap-southeast-2", help="AWS region")
    parser.add_argument("--cluster", default="clawtalk-dev", help="ECS cluster name")
    parser.add_argument("--container", default="openclaw-agent", help="Container name")
    parser.add_argument(
        "--command", default="/bin/bash", help="Command to execute (default: /bin/bash)"
    )

    args = parser.parse_args()

    # Determine task ARN
    if args.task_arn:
        task_arn = args.task_arn
    elif args.container_id and args.user_id:
        task_arn = get_task_arn(
            args.container_id, args.user_id, args.env, args.profile, args.region
        )
    else:
        parser.error("Either provide CONTAINER_ID with --user-id, or use --task-arn")

    exec_shell(
        task_arn, args.cluster, args.container, args.profile, args.region, args.command
    )


if __name__ == "__main__":
    main()
