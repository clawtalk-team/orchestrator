#!/usr/bin/env python3
"""
Get logs for a specific openclaw-agent container.
Fetches CloudWatch logs filtered by task ID.

Usage:
  python scripts/get_logs.py CONTAINER_ID --user-id USER_ID [--env ENV]
  python scripts/get_logs.py --task-id TASK_ID [--env ENV]
"""

import argparse
import sys
import time
from datetime import datetime, timedelta

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


def tail_logs(
    task_id: str,
    env: str,
    profile: str,
    region: str,
    follow: bool = False,
    since_minutes: int = 30,
):
    """Tail CloudWatch logs for a task."""
    log_group = f"/ecs/openclaw-agent-{env}"

    session = boto3.Session(profile_name=profile, region_name=region)
    logs = session.client("logs")

    print(f"==> Fetching logs from {log_group}")
    print(f"    Task ID: {task_id}")
    print()

    # Get log streams that match the task ID
    start_time = int(
        (datetime.now() - timedelta(minutes=since_minutes)).timestamp() * 1000
    )

    try:
        # Use filter_log_events to search across all streams
        kwargs = {
            "logGroupName": log_group,
            "startTime": start_time,
            "filterPattern": task_id,
            "limit": 100,
        }

        if follow:
            print("Following logs (Ctrl+C to stop)...")
            last_timestamp = start_time

            try:
                while True:
                    kwargs["startTime"] = last_timestamp

                    # Fetch all events with pagination
                    while True:
                        response = logs.filter_log_events(**kwargs)
                        events = response.get("events", [])

                        for event in events:
                            timestamp = datetime.fromtimestamp(
                                event["timestamp"] / 1000
                            )
                            message = event["message"].rstrip()
                            print(
                                f"{timestamp.strftime('%Y-%m-%d %H:%M:%S')} {message}"
                            )
                            last_timestamp = max(last_timestamp, event["timestamp"] + 1)

                        # Handle pagination
                        if "nextToken" in response:
                            kwargs["nextToken"] = response["nextToken"]
                        else:
                            break

                    # Remove nextToken for next iteration
                    kwargs.pop("nextToken", None)

                    if not events:
                        time.sleep(2)

            except KeyboardInterrupt:
                print("\n==> Stopped following logs")
        else:
            # Fetch all events with pagination
            all_events = []
            while True:
                response = logs.filter_log_events(**kwargs)
                all_events.extend(response.get("events", []))

                if "nextToken" in response:
                    kwargs["nextToken"] = response["nextToken"]
                else:
                    break

            if not all_events:
                print(
                    f"No logs found for task {task_id} in the last {since_minutes} minutes"
                )
                return

            for event in all_events:
                timestamp = datetime.fromtimestamp(event["timestamp"] / 1000)
                message = event["message"].rstrip()
                print(f"{timestamp.strftime('%Y-%m-%d %H:%M:%S')} {message}")

            print(f"\n==> Showing logs from last {since_minutes} minutes")
            print("==> To follow logs in real-time, use --follow")

    except logs.exceptions.ResourceNotFoundException:
        print(f"Error: Log group {log_group} not found")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Get logs for openclaw-agent container"
    )
    parser.add_argument(
        "container_id", nargs="?", help="Container ID (e.g., oc-abc12345)"
    )
    parser.add_argument("--user-id", help="User ID who owns the container")
    parser.add_argument(
        "--task-id", help="Task ID to fetch logs for (alternative to container-id)"
    )
    parser.add_argument("--env", default="dev", help="Environment (dev/prod)")
    parser.add_argument("--profile", default="personal", help="AWS profile name")
    parser.add_argument("--region", default="ap-southeast-2", help="AWS region")
    parser.add_argument(
        "--follow", "-f", action="store_true", help="Follow logs in real-time"
    )
    parser.add_argument(
        "--since",
        type=int,
        default=30,
        help="Show logs from last N minutes (default: 30)",
    )

    args = parser.parse_args()

    # Determine task ID
    if args.task_id:
        task_id = args.task_id
    elif args.container_id and args.user_id:
        task_arn = get_task_arn(
            args.container_id, args.user_id, args.env, args.profile, args.region
        )
        task_id = task_arn.split("/")[-1]
    else:
        parser.error("Either provide CONTAINER_ID with --user-id, or use --task-id")

    tail_logs(
        task_id,
        args.env,
        args.profile,
        args.region,
        follow=args.follow,
        since_minutes=args.since,
    )


if __name__ == "__main__":
    main()
