#!/usr/bin/env python3
"""
Inspect the status of an agent/container by ID.
Useful for diagnosing failed or stuck container creation.

Accepts either:
  - A full UUID: e20ac9f1-2d3a-462c-9a37-205779ac0e0a
  - A container ID: oc-e20ac9f1

Looks up the DynamoDB record, ECS task status, and CloudWatch logs.

Usage:
  python scripts/inspect_agent.py e20ac9f1-2d3a-462c-9a37-205779ac0e0a
  python scripts/inspect_agent.py oc-e20ac9f1
  python scripts/inspect_agent.py oc-e20ac9f1 --logs --since 60
"""

import argparse
import sys
from datetime import datetime, timedelta

import boto3


def normalize_container_id(agent_id: str) -> tuple[str, str | None]:
    """
    Return (container_id, ecs_task_id_or_none).

    - Full UUID (e20ac9f1-2d3a-462c-9a37-205779ac0e0a):
        container_id = oc-e20ac9f1
        ecs_task_id  = e20ac9f12d3a462c9a37205779ac0e0a  (also try as ECS task)
    - oc- format:
        container_id = oc-e20ac9f1
        ecs_task_id  = None
    """
    if agent_id.startswith("oc-"):
        return agent_id, None
    # It's a UUID — derive both representations
    hex_no_dashes = agent_id.replace("-", "")
    container_id = f"oc-{hex_no_dashes[:8]}"
    return container_id, hex_no_dashes


def find_container_in_dynamodb(
    container_id: str,
    table_name: str,
    session: boto3.Session,
    ecs_task_id: str | None = None,
) -> dict | None:
    """Scan DynamoDB to find a container record by container_id or task_arn."""
    dynamodb = session.client("dynamodb")

    # Try by container sk first
    scan_kwargs = {
        "TableName": table_name,
        "FilterExpression": "sk = :sk",
        "ExpressionAttributeValues": {":sk": {"S": f"CONTAINER#{container_id}"}},
    }

    items = []
    while True:
        response = dynamodb.scan(**scan_kwargs)
        items.extend(response.get("Items", []))
        if "LastEvaluatedKey" not in response:
            break
        scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

    if items:
        return items[0]

    # If not found and we have a full task UUID, try scanning by task_arn
    if ecs_task_id:
        scan_kwargs = {
            "TableName": table_name,
            "FilterExpression": "contains(task_arn, :task_id)",
            "ExpressionAttributeValues": {":task_id": {"S": ecs_task_id}},
        }
        items = []
        while True:
            response = dynamodb.scan(**scan_kwargs)
            items.extend(response.get("Items", []))
            if "LastEvaluatedKey" not in response:
                break
            scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

        if items:
            return items[0]

    return None


def print_section(title: str) -> None:
    width = 60
    print(f"\n{'=' * width}")
    print(f"  {title}")
    print(f"{'=' * width}")


def inspect_dynamodb(item: dict) -> dict:
    """Print and return the DynamoDB container record."""
    print_section("DynamoDB Record")

    def get(key):
        val = item.get(key, {})
        return val.get("S") or val.get("N") or val.get("BOOL") or ""

    fields = {
        "Container ID": get("sk").replace("CONTAINER#", ""),
        "User ID": get("user_id"),
        "Status": get("status"),
        "Health Status": get("health_status"),
        "IP Address": get("ip_address"),
        "Task ARN": get("task_arn"),
        "Created At": get("created_at"),
        "Updated At": get("updated_at"),
    }

    for k, v in fields.items():
        if v:
            print(f"  {k:<16} {v}")
        else:
            print(f"  {k:<16} (not set)")

    return fields


def inspect_ecs_task(task_arn: str, cluster: str, session: boto3.Session) -> None:
    """Describe the ECS task and print its status."""
    print_section("ECS Task Status")

    if not task_arn or task_arn in ("None", ""):
        print("  No task ARN — ECS task was never created or ARN was not stored.")
        return

    ecs = session.client("ecs")
    task_id = task_arn.split("/")[-1]

    try:
        response = ecs.describe_tasks(
            cluster=cluster,
            tasks=[task_id],
            include=["TAGS"],
        )
    except Exception as e:
        print(f"  Error describing ECS task: {e}")
        return

    failures = response.get("failures", [])
    if failures:
        for f in failures:
            print(f"  ECS failure: {f.get('reason')} (arn={f.get('arn')})")
        return

    tasks = response.get("tasks", [])
    if not tasks:
        print("  Task not found in ECS (may have been cleaned up).")
        return

    task = tasks[0]
    print(f"  Task ID:          {task_id}")
    print(f"  Last Status:      {task.get('lastStatus')}")
    print(f"  Desired Status:   {task.get('desiredStatus')}")
    print(f"  Health Status:    {task.get('healthStatus', 'N/A')}")
    print(f"  Launch Type:      {task.get('launchType')}")
    print(f"  Created At:       {task.get('createdAt')}")
    print(f"  Started At:       {task.get('startedAt', '(not started)')}")
    print(f"  Stopped At:       {task.get('stoppedAt', '(not stopped)')}")

    stopped_reason = task.get("stoppedReason")
    if stopped_reason:
        print(f"  Stopped Reason:   {stopped_reason}")

    containers = task.get("containers", [])
    if containers:
        print(f"\n  Containers ({len(containers)}):")
        for c in containers:
            print(f"    - {c.get('name')}")
            print(f"        Status:       {c.get('lastStatus')}")
            print(f"        Exit Code:    {c.get('exitCode', '(n/a)')}")
            reason = c.get("reason")
            if reason:
                print(f"        Reason:       {reason}")


def inspect_orchestrator_invocations(
    env: str, created_at: str | None, session: boto3.Session
) -> None:
    """Show Lambda invocations around the container creation time."""
    print_section("Orchestrator Lambda Invocations")
    print("  Note: only START/END/REPORT are captured — app-level logs are not emitted to CloudWatch.")
    print()

    if not created_at:
        print("  No creation timestamp available — cannot narrow down invocations.")
        return

    log_group = f"/aws/lambda/orchestrator-{env}"
    logs = session.client("logs")

    try:
        # Parse created_at and build a ±2 minute window
        created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        start_ms = int((created_dt - timedelta(minutes=2)).timestamp() * 1000)
        end_ms = int((created_dt + timedelta(minutes=2)).timestamp() * 1000)

        kwargs = {
            "logGroupName": log_group,
            "startTime": start_ms,
            "endTime": end_ms,
            "filterPattern": "START",
            "limit": 20,
        }
        response = logs.filter_log_events(**kwargs)
        events = response.get("events", [])

        if not events:
            print(f"  No Lambda invocations found in ±2 min window around {created_at}.")
            print("  The orchestrator may not have received the request.")
        else:
            print(f"  Invocations near creation time ({created_at}):")
            for event in events:
                ts = datetime.fromtimestamp(event["timestamp"] / 1000)
                print(f"  {ts.strftime('%Y-%m-%d %H:%M:%S')}  {event['message'].rstrip()}")

    except logs.exceptions.ResourceNotFoundException:
        print(f"  Log group not found: {log_group}")
    except Exception as e:
        print(f"  Error: {e}")


def inspect_logs(
    task_arn: str, env: str, session: boto3.Session, since_minutes: int = 30
) -> None:
    """Fetch CloudWatch logs for the task."""
    print_section(f"CloudWatch Logs (last {since_minutes} minutes)")

    if not task_arn or task_arn in ("None", ""):
        print("  No task ARN — cannot fetch logs.")
        return

    task_id = task_arn.split("/")[-1]
    log_group = f"/ecs/openclaw-agent-{env}"
    logs = session.client("logs")

    start_time = int(
        (datetime.now() - timedelta(minutes=since_minutes)).timestamp() * 1000
    )

    try:
        kwargs = {
            "logGroupName": log_group,
            "startTime": start_time,
            "filterPattern": task_id,
            "limit": 200,
        }

        all_events = []
        while True:
            response = logs.filter_log_events(**kwargs)
            all_events.extend(response.get("events", []))
            if "nextToken" in response:
                kwargs["nextToken"] = response["nextToken"]
            else:
                break

        if not all_events:
            print(f"  No logs found for task {task_id} in the last {since_minutes} minutes.")
            print(f"  Log group: {log_group}")
            return

        print(f"  Log group: {log_group}")
        print(f"  Task ID:   {task_id}")
        print()
        for event in all_events:
            ts = datetime.fromtimestamp(event["timestamp"] / 1000)
            print(f"  {ts.strftime('%Y-%m-%d %H:%M:%S')}  {event['message'].rstrip()}")

    except logs.exceptions.ResourceNotFoundException:
        print(f"  Log group not found: {log_group}")
    except Exception as e:
        print(f"  Error fetching logs: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Inspect agent/container status by ID",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Inspect by full UUID
  %(prog)s e20ac9f1-2d3a-462c-9a37-205779ac0e0a

  # Inspect by oc- container ID
  %(prog)s oc-e20ac9f1

  # Include logs (last 60 minutes)
  %(prog)s oc-e20ac9f1 --logs --since 60

  # Use prod environment
  %(prog)s oc-e20ac9f1 --env prod
        """,
    )

    parser.add_argument("agent_id", help="Agent/container ID (UUID or oc- format)")
    parser.add_argument("--env", default="dev", help="Environment (dev/prod)")
    parser.add_argument("--profile", default="personal", help="AWS profile name")
    parser.add_argument("--region", default="ap-southeast-2", help="AWS region")
    parser.add_argument(
        "--logs", action="store_true", help="Fetch CloudWatch logs"
    )
    parser.add_argument(
        "--since",
        type=int,
        default=60,
        help="Search logs from last N minutes (default: 60)",
    )
    parser.add_argument(
        "--cluster",
        help="ECS cluster name (default: clawtalk-{env})",
    )

    args = parser.parse_args()

    container_id, ecs_task_id = normalize_container_id(args.agent_id)
    table_name = f"openclaw-containers-{args.env}"
    cluster = args.cluster or f"clawtalk-{args.env}"

    session = boto3.Session(profile_name=args.profile, region_name=args.region)

    print(f"Inspecting agent: {args.agent_id}")
    print(f"  Container ID: {container_id}")
    if ecs_task_id:
        print(f"  ECS Task ID:  {ecs_task_id}")
    print(f"  Table:        {table_name}")
    print(f"  Cluster:      {cluster}")

    # 1. Find in DynamoDB
    item = find_container_in_dynamodb(container_id, table_name, session, ecs_task_id)

    if not item:
        print_section("DynamoDB Record")
        print(f"  NOT FOUND — container '{container_id}' has no record in '{table_name}'.")
        print("  This means the failure occurred before or during the DynamoDB write step.")
        task_arn_for_logs = None
        created_at = None
    else:
        fields = inspect_dynamodb(item)
        task_arn_for_logs = fields.get("Task ARN")
        created_at = fields.get("Created At")

        # 2. Check ECS task
        inspect_ecs_task(task_arn_for_logs, cluster, session)

    # 3. Show orchestrator Lambda invocations near creation time
    inspect_orchestrator_invocations(args.env, created_at, session)

    # 4. Optionally fetch container (ECS task) logs
    if args.logs and task_arn_for_logs:
        inspect_logs(task_arn_for_logs, args.env, session, since_minutes=args.since)
    elif args.logs:
        print_section("CloudWatch Logs")
        print("  No task ARN available — cannot fetch container logs.")
    else:
        print(f"\n  Tip: re-run with --logs to also fetch container (ECS) CloudWatch logs")

    print()


if __name__ == "__main__":
    main()
