#!/usr/bin/env python3
"""
Clawtalk orchestrator management CLI.

Usage:
  manage.py <group> <command> [options]

Groups and commands:
  containers list       List containers from DynamoDB
  containers launch     Launch a new container via the orchestrator API
  containers delete     Delete one or more containers (stops ECS task + removes DB record)
  containers inspect    Inspect container/agent status (DynamoDB + ECS + logs)
  containers logs       Fetch CloudWatch logs for a container
  containers exec       Open an interactive shell on a running container

  ecs list              List all ECS tasks in the cluster
  ecs stop-all          Stop all running ECS tasks
  ecs cleanup           Remove PENDING and FAILED tasks from ECS and DynamoDB

  config load           Load system or user defaults into DynamoDB
  config setup-test     Bootstrap local test config in DynamoDB

  verify                Verify AWS credentials and service connectivity

Common options (most commands):
  --env ENV             Environment: dev or prod (default: dev)
  --profile PROFILE     AWS profile name (default: personal)
  --region REGION       AWS region (default: ap-southeast-2)
  --cluster CLUSTER     ECS cluster name (default: clawtalk-{env})

Examples:
  manage.py containers list
  manage.py containers list --env prod --user-id abc123
  manage.py containers launch --user-id USER --token TOKEN --wait
  manage.py containers delete oc-abc123 --user-id USER
  manage.py containers delete --all --status STOPPED
  manage.py containers inspect oc-abc123 --logs
  manage.py containers logs oc-abc123 --user-id USER --follow
  manage.py containers exec oc-abc123 --user-id USER
  manage.py ecs list
  manage.py ecs stop-all --dry-run
  manage.py ecs cleanup --dry-run
  manage.py config load --system --auth-gateway-url https://...
  manage.py config load --user-id abc123 --anthropic-api-key sk-ant-...
  manage.py config setup-test --user-id test-user --anthropic-key sk-ant-...
  manage.py verify
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import boto3
import requests
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from tabulate import tabulate

load_dotenv()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def make_boto_session(profile: str, region: str) -> boto3.Session:
    return boto3.Session(profile_name=profile, region_name=region)


def resolve_cluster(env: str, cluster: Optional[str]) -> str:
    return cluster or f"clawtalk-{env}"


def resolve_table(env: str) -> str:
    return f"openclaw-containers-{env}"


COMMON_ARGS = [
    (["--env"], {"default": "dev", "metavar": "ENV", "help": "Environment: dev or prod (default: dev)"}),
    (["--profile"], {"default": "personal", "metavar": "PROFILE", "help": "AWS profile name (default: personal)"}),
    (["--region"], {"default": "ap-southeast-2", "metavar": "REGION", "help": "AWS region (default: ap-southeast-2)"}),
    (["--cluster"], {"default": None, "metavar": "CLUSTER", "help": "ECS cluster name (default: clawtalk-{env})"}),
]


def add_common(parser: argparse.ArgumentParser) -> None:
    for flags, kwargs in COMMON_ARGS:
        parser.add_argument(*flags, **kwargs)


def _has_task_arn(arn: Optional[str]) -> bool:
    return bool(arn and arn not in ("None", ""))


def _fmt_log_ts(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _dynamo_paginate(client_method, **kwargs) -> list:
    items = []
    while True:
        response = client_method(**kwargs)
        items.extend(response.get("Items", []))
        if "LastEvaluatedKey" not in response:
            break
        kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
    return items


def _ecs_list_task_arns(ecs_client, **kwargs) -> list:
    arns = []
    while True:
        response = ecs_client.list_tasks(**kwargs)
        arns.extend(response.get("taskArns", []))
        if "nextToken" not in response:
            break
        kwargs["nextToken"] = response["nextToken"]
    return arns


def _fetch_all_log_events(logs_client, **kwargs) -> list:
    events = []
    while True:
        response = logs_client.filter_log_events(**kwargs)
        events.extend(response.get("events", []))
        if "nextToken" not in response:
            break
        kwargs["nextToken"] = response["nextToken"]
    return events


# ---------------------------------------------------------------------------
# containers list
# ---------------------------------------------------------------------------


def cmd_containers_list(args) -> int:
    table_name = resolve_table(args.env)
    session = make_boto_session(args.profile, args.region)
    dynamodb = session.client("dynamodb")

    print(f"==> Listing containers from DynamoDB table: {table_name}\n")

    if args.user_id:
        print(f"Filtering by user: {args.user_id}")
        container_items = _dynamo_paginate(
            dynamodb.query,
            TableName=table_name,
            KeyConditionExpression="pk = :pk AND begins_with(sk, :sk_prefix)",
            ExpressionAttributeValues={
                ":pk": {"S": f"USER#{args.user_id}"},
                ":sk_prefix": {"S": "CONTAINER#"},
            },
        )
    else:
        container_items = [
            item for item in _dynamo_paginate(dynamodb.scan, TableName=table_name)
            if item.get("sk", {}).get("S", "").startswith("CONTAINER#")
        ]

    if not container_items:
        print("No containers found.")
        return 0

    table_data = []
    for item in container_items:
        container_id = item.get("sk", {}).get("S", "").replace("CONTAINER#", "")
        user = item.get("user_id", {}).get("S", "")
        status = item.get("status", {}).get("S", "")
        task_arn = item.get("task_arn", {}).get("S", "")
        ip = item.get("ip_address", {}).get("S", "")
        created = item.get("created_at", {}).get("S", "")
        health = item.get("health_status", {}).get("S", "")
        table_data.append([
            container_id, user, status, health, ip,
            task_arn.split("/")[-1] if task_arn else "",
            created,
        ])

    headers = ["Container ID", "User ID", "Status", "Health", "IP Address", "Task ID", "Created At"]
    print(tabulate(table_data, headers=headers, tablefmt="grid"))
    print(f"\nTotal containers: {len(container_items)}")
    return 0


# ---------------------------------------------------------------------------
# containers launch
# ---------------------------------------------------------------------------


def cmd_containers_launch(args) -> int:
    if args.url:
        base_url = args.url.rstrip("/")
    elif args.local:
        base_url = "http://localhost:8000"
    else:
        urls = {
            "dev": "https://prz6mum7c7.execute-api.ap-southeast-2.amazonaws.com",
            "prod": "https://api.openclaw.ai",
        }
        base_url = urls.get(args.env, urls["dev"])

    config = None
    if args.config:
        try:
            config = json.loads(args.config)
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in --config: {e}")
            return 1

    auth_token = f"{args.user_id}:{args.token}"
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
    }

    body: dict = {}
    if args.name:
        body["name"] = args.name
    if config:
        body["config"] = config

    print(f"==> Launching container via {base_url}/containers")
    if args.name:
        print(f"    Name: {args.name}")
    if config:
        print(f"    Config: {json.dumps(config, indent=2)}")
    print()

    try:
        response = requests.post(f"{base_url}/containers", headers=headers, json=body, timeout=30)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error creating container: {e}")
        if hasattr(e, "response") and e.response is not None:
            print(f"Response: {e.response.text}")
        return 1

    container = response.json()
    print(f"Container created successfully!")
    print(f"\n{'='*60}")
    print(f"Container ID:    {container['container_id']}")
    print(f"Status:          {container['status']}")
    print(f"Health Status:   {container['health_status']}")
    print(f"IP Address:      {container.get('ip_address', 'Not yet assigned')}")
    print(f"Created At:      {container['created_at']}")
    print(f"{'='*60}\n")

    if args.wait:
        container_id = container["container_id"]
        start_time = time.time()
        print(f"Waiting for container to become healthy (timeout: {args.wait_timeout}s)...")

        while time.time() - start_time < args.wait_timeout:
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
                    print(f"\nContainer is now HEALTHY!")
                    break
                elif health_status in ("UNHEALTHY", "FAILED"):
                    print(f"\nContainer is {health_status}")
                    return 1

                time.sleep(5)
            except requests.exceptions.RequestException as e:
                print(f"\nError checking health: {e}")
                break
        else:
            print(f"\nTimeout waiting for container to become healthy")

    print(f"\n==> Next steps:")
    print(f"  manage.py containers logs {container['container_id']} --user-id {args.user_id}")
    print(f"  manage.py containers exec {container['container_id']} --user-id {args.user_id}")
    print(f"  manage.py containers delete {container['container_id']} --user-id {args.user_id}")
    return 0


# ---------------------------------------------------------------------------
# containers delete
# ---------------------------------------------------------------------------


def _get_containers_for_delete(
    user_id: Optional[str],
    env: str,
    profile: str,
    region: str,
    status: Optional[str] = None,
) -> List[dict]:
    table_name = resolve_table(env)
    session = make_boto_session(profile, region)
    dynamodb = session.client("dynamodb")

    if user_id:
        print(f"==> Fetching containers for user {user_id}...")
        kwargs: dict = {
            "TableName": table_name,
            "KeyConditionExpression": "pk = :pk AND begins_with(sk, :sk_prefix)",
            "ExpressionAttributeValues": {
                ":pk": {"S": f"USER#{user_id}"},
                ":sk_prefix": {"S": "CONTAINER#"},
            },
        }
        if status:
            kwargs["FilterExpression"] = "#s = :status"
            kwargs["ExpressionAttributeNames"] = {"#s": "status"}
            kwargs["ExpressionAttributeValues"][":status"] = {"S": status}
        return [_parse_container_item(item) for item in _dynamo_paginate(dynamodb.query, **kwargs)]
    else:
        print(f"==> Fetching all containers (system-wide)...")
        kwargs = {"TableName": table_name}
        if status:
            kwargs["FilterExpression"] = "#s = :status"
            kwargs["ExpressionAttributeNames"] = {"#s": "status"}
            kwargs["ExpressionAttributeValues"] = {":status": {"S": status}}
        return [
            _parse_container_item(item)
            for item in _dynamo_paginate(dynamodb.scan, **kwargs)
            if item.get("sk", {}).get("S", "").startswith("CONTAINER#")
        ]


def _parse_container_item(item: dict) -> dict:
    return {
        "container_id": item.get("sk", {}).get("S", "").replace("CONTAINER#", ""),
        "user_id": item.get("user_id", {}).get("S", ""),
        "status": item.get("status", {}).get("S", ""),
        "task_arn": item.get("task_arn", {}).get("S", ""),
        "created_at": item.get("created_at", {}).get("S", ""),
        "pk": item.get("pk", {}).get("S", ""),
        "sk": item.get("sk", {}).get("S", ""),
    }


def _delete_one_container(container: dict, env: str, cluster: str, dry_run: bool, *, ecs, dynamodb) -> None:
    container_id = container["container_id"]
    task_arn = container["task_arn"]
    table_name = resolve_table(env)

    print(f"\n==> Deleting container: {container_id}")
    print(f"    Status: {container['status']}")
    print(f"    Task ARN: {task_arn}")

    if dry_run:
        print("    [DRY RUN - no changes made]")
        return

    if _has_task_arn(task_arn):
        try:
            print("    Stopping ECS task...")
            ecs.stop_task(
                cluster=cluster,
                task=task_arn,
                reason=f"Container {container_id} deleted via manage.py",
            )
            print("    ECS task stopped")
        except ClientError as e:
            if "not found" in str(e).lower():
                print("    Task not found in ECS (may already be stopped)")
            else:
                print(f"    Error stopping task: {e}")

    try:
        print("    Deleting DynamoDB record...")
        dynamodb.delete_item(
            TableName=table_name,
            Key={"pk": {"S": container["pk"]}, "sk": {"S": container["sk"]}},
        )
        print("    DynamoDB record deleted")
    except Exception as e:
        print(f"    Error deleting from DynamoDB: {e}")


def cmd_containers_delete(args) -> int:
    if args.container_ids and not args.user_id:
        print("Error: --user-id is required when specifying container IDs")
        return 1

    cluster = resolve_cluster(args.env, args.cluster)
    session = make_boto_session(args.profile, args.region)
    ecs = session.client("ecs")
    dynamodb = session.client("dynamodb")
    table_name = resolve_table(args.env)
    containers_to_delete = []

    if args.all or args.status:
        containers_to_delete = _get_containers_for_delete(
            args.user_id, args.env, args.profile, args.region, status=args.status
        )
        if not containers_to_delete:
            print("No containers found matching criteria.")
            return 0

    elif args.container_ids:
        for container_id in args.container_ids:
            response = dynamodb.get_item(
                TableName=table_name,
                Key={
                    "pk": {"S": f"USER#{args.user_id}"},
                    "sk": {"S": f"CONTAINER#{container_id}"},
                },
            )
            item = response.get("Item")
            if not item:
                print(f"Warning: Container {container_id} not found")
                continue
            containers_to_delete.append(_parse_container_item(item))
    else:
        print("Error: Provide container IDs, --all, or --status")
        return 1

    print(f"\n{'=' * 60}")
    print(f"Containers to delete ({len(containers_to_delete)}):")
    print(f"{'=' * 60}")
    for container in containers_to_delete:
        print(f"  - {container['container_id']} (Status: {container['status']})")

    if args.dry_run:
        print("\n[DRY RUN MODE - no changes will be made]")
    elif not args.yes:
        response = input(f"\nDelete {len(containers_to_delete)} container(s)? [y/N]: ")
        if response.lower() not in ("y", "yes"):
            print("Aborted.")
            return 0

    for container in containers_to_delete:
        _delete_one_container(container, args.env, cluster, args.dry_run, ecs=ecs, dynamodb=dynamodb)

    print(f"\n{'=' * 60}")
    if args.dry_run:
        print(f"DRY RUN: Would have deleted {len(containers_to_delete)} container(s)")
    else:
        print(f"Deleted {len(containers_to_delete)} container(s)")
    return 0


# ---------------------------------------------------------------------------
# containers inspect
# ---------------------------------------------------------------------------


def _normalize_agent_id(agent_id: str) -> tuple[str, Optional[str]]:
    if agent_id.startswith("oc-"):
        return agent_id, None
    hex_no_dashes = agent_id.replace("-", "")
    container_id = f"oc-{hex_no_dashes[:8]}"
    return container_id, hex_no_dashes


def _find_container_in_db(container_id: str, table_name: str, session: boto3.Session, ecs_task_id: Optional[str]) -> Optional[dict]:
    dynamodb = session.client("dynamodb")

    items = _dynamo_paginate(
        dynamodb.scan,
        TableName=table_name,
        FilterExpression="sk = :sk",
        ExpressionAttributeValues={":sk": {"S": f"CONTAINER#{container_id}"}},
    )
    if items:
        return items[0]

    if ecs_task_id:
        items = _dynamo_paginate(
            dynamodb.scan,
            TableName=table_name,
            FilterExpression="contains(task_arn, :task_id)",
            ExpressionAttributeValues={":task_id": {"S": ecs_task_id}},
        )
        if items:
            return items[0]

    return None


def _print_section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def _inspect_dynamodb(item: dict) -> dict:
    _print_section("DynamoDB Record")

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
        print(f"  {k:<16} {v or '(not set)'}")
    return fields


def _inspect_ecs_task(task_arn: str, cluster: str, session: boto3.Session) -> None:
    _print_section("ECS Task Status")
    if not _has_task_arn(task_arn):
        print("  No task ARN — ECS task was never created or ARN was not stored.")
        return

    ecs = session.client("ecs")
    task_id = task_arn.split("/")[-1]
    try:
        response = ecs.describe_tasks(cluster=cluster, tasks=[task_id], include=["TAGS"])
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
    if task.get("stoppedReason"):
        print(f"  Stopped Reason:   {task['stoppedReason']}")
    for c in task.get("containers", []):
        print(f"\n  Container: {c.get('name')}")
        print(f"    Status:    {c.get('lastStatus')}")
        print(f"    Exit Code: {c.get('exitCode', '(n/a)')}")
        if c.get("reason"):
            print(f"    Reason:    {c['reason']}")


def _inspect_lambda_invocations(env: str, created_at: Optional[str], session: boto3.Session) -> None:
    _print_section("Orchestrator Lambda Invocations")
    print("  Note: only START/END/REPORT are captured — app-level logs are not emitted to CloudWatch.")
    if not created_at:
        print("  No creation timestamp — cannot narrow down invocations.")
        return

    log_group = f"/aws/lambda/orchestrator-{env}"
    logs = session.client("logs")
    try:
        created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        start_ms = int((created_dt - timedelta(minutes=2)).timestamp() * 1000)
        end_ms = int((created_dt + timedelta(minutes=2)).timestamp() * 1000)
        response = logs.filter_log_events(
            logGroupName=log_group, startTime=start_ms, endTime=end_ms,
            filterPattern="START", limit=20,
        )
        events = response.get("events", [])
        if not events:
            print(f"  No Lambda invocations found in ±2 min window around {created_at}.")
        else:
            print(f"  Invocations near creation time ({created_at}):")
            for event in events:
                print(f"  {_fmt_log_ts(event['timestamp'])}  {event['message'].rstrip()}")
    except logs.exceptions.ResourceNotFoundException:
        print(f"  Log group not found: {log_group}")
    except Exception as e:
        print(f"  Error: {e}")


def _inspect_logs(task_arn: str, env: str, session: boto3.Session, since_minutes: int) -> None:
    _print_section(f"CloudWatch Logs (last {since_minutes} minutes)")
    if not _has_task_arn(task_arn):
        print("  No task ARN — cannot fetch logs.")
        return

    task_id = task_arn.split("/")[-1]
    log_group = f"/ecs/openclaw-agent-{env}"
    logs = session.client("logs")
    start_time = int((datetime.now() - timedelta(minutes=since_minutes)).timestamp() * 1000)

    try:
        all_events = _fetch_all_log_events(
            logs,
            logGroupName=log_group,
            startTime=start_time,
            filterPattern=task_id,
            limit=200,
        )

        if not all_events:
            print(f"  No logs found for task {task_id} in the last {since_minutes} minutes.")
            return

        print(f"  Log group: {log_group}")
        print(f"  Task ID:   {task_id}\n")
        for event in all_events:
            print(f"  {_fmt_log_ts(event['timestamp'])}  {event['message'].rstrip()}")

    except logs.exceptions.ResourceNotFoundException:
        print(f"  Log group not found: {log_group}")
    except Exception as e:
        print(f"  Error fetching logs: {e}")


def cmd_containers_inspect(args) -> int:
    container_id, ecs_task_id = _normalize_agent_id(args.agent_id)
    table_name = resolve_table(args.env)
    cluster = resolve_cluster(args.env, args.cluster)

    session = make_boto_session(args.profile, args.region)

    print(f"Inspecting agent: {args.agent_id}")
    print(f"  Container ID: {container_id}")
    if ecs_task_id:
        print(f"  ECS Task ID:  {ecs_task_id}")
    print(f"  Table:        {table_name}")
    print(f"  Cluster:      {cluster}")

    item = _find_container_in_db(container_id, table_name, session, ecs_task_id)

    if not item:
        _print_section("DynamoDB Record")
        print(f"  NOT FOUND — container '{container_id}' has no record in '{table_name}'.")
        task_arn_for_logs = None
        created_at = None
    else:
        fields = _inspect_dynamodb(item)
        task_arn_for_logs = fields.get("Task ARN")
        created_at = fields.get("Created At")
        _inspect_ecs_task(task_arn_for_logs, cluster, session)

    _inspect_lambda_invocations(args.env, created_at, session)

    if args.logs and task_arn_for_logs:
        _inspect_logs(task_arn_for_logs, args.env, session, since_minutes=args.since)
    elif args.logs:
        _print_section("CloudWatch Logs")
        print("  No task ARN available — cannot fetch container logs.")
    else:
        print(f"\n  Tip: re-run with --logs to also fetch container CloudWatch logs")

    print()
    return 0


# ---------------------------------------------------------------------------
# containers logs
# ---------------------------------------------------------------------------


def _get_task_arn_from_db(container_id: str, user_id: str, env: str, profile: str, region: str) -> str:
    table_name = resolve_table(env)
    session = make_boto_session(profile, region)
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
    if not _has_task_arn(task_arn):
        print(f"Error: No task ARN set for container {container_id}")
        sys.exit(1)
    return task_arn


def cmd_containers_logs(args) -> int:
    if args.task_id:
        task_id = args.task_id
    elif args.container_id and args.user_id:
        task_arn = _get_task_arn_from_db(args.container_id, args.user_id, args.env, args.profile, args.region)
        task_id = task_arn.split("/")[-1]
    else:
        print("Error: Either provide CONTAINER_ID with --user-id, or use --task-id")
        return 1

    log_group = f"/ecs/openclaw-agent-{args.env}"
    session = make_boto_session(args.profile, args.region)
    logs = session.client("logs")

    print(f"==> Fetching logs from {log_group}")
    print(f"    Task ID: {task_id}\n")

    start_time = int((datetime.now() - timedelta(minutes=args.since)).timestamp() * 1000)

    try:
        kwargs: dict = {
            "logGroupName": log_group,
            "startTime": start_time,
            "filterPattern": task_id,
            "limit": 100,
        }

        if args.follow:
            print("Following logs (Ctrl+C to stop)...")
            last_timestamp = start_time
            try:
                while True:
                    kwargs["startTime"] = last_timestamp
                    saw_events = False
                    while True:
                        response = logs.filter_log_events(**kwargs)
                        for event in response.get("events", []):
                            print(f"{_fmt_log_ts(event['timestamp'])} {event['message'].rstrip()}")
                            last_timestamp = max(last_timestamp, event["timestamp"] + 1)
                            saw_events = True
                        if "nextToken" in response:
                            kwargs["nextToken"] = response["nextToken"]
                        else:
                            break
                    kwargs.pop("nextToken", None)
                    if not saw_events:
                        time.sleep(2)
            except KeyboardInterrupt:
                print("\n==> Stopped following logs")
        else:
            all_events = _fetch_all_log_events(logs, **kwargs)

            if not all_events:
                print(f"No logs found for task {task_id} in the last {args.since} minutes")
                return 0

            for event in all_events:
                print(f"{_fmt_log_ts(event['timestamp'])} {event['message'].rstrip()}")

            print(f"\n==> Showing logs from last {args.since} minutes")
            print("==> To follow logs in real-time, use --follow")

    except logs.exceptions.ResourceNotFoundException:
        print(f"Error: Log group {log_group} not found")
        return 1

    return 0


# ---------------------------------------------------------------------------
# containers exec
# ---------------------------------------------------------------------------


def cmd_containers_exec(args) -> int:
    if args.task_arn:
        task_arn = args.task_arn
    elif args.container_id and args.user_id:
        task_arn = _get_task_arn_from_db(args.container_id, args.user_id, args.env, args.profile, args.region)
    else:
        print("Error: Either provide CONTAINER_ID with --user-id, or use --task-arn")
        return 1

    cluster = resolve_cluster(args.env, args.cluster)
    task_id = task_arn.split("/")[-1]

    print(f"==> Connecting to task: {task_id}")
    print(f"    Cluster: {cluster}")
    print(f"    Container: {args.container}\n")

    cmd = [
        "aws", "ecs", "execute-command",
        "--profile", args.profile,
        "--region", args.region,
        "--cluster", cluster,
        "--task", task_id,
        "--container", args.container,
        "--interactive",
        "--command", args.command,
    ]

    try:
        result = subprocess.run(cmd)
        return result.returncode
    except FileNotFoundError:
        print("Error: AWS CLI not found. Please install the AWS CLI.")
        return 1
    except KeyboardInterrupt:
        print("\n==> Session interrupted")
        return 0


# ---------------------------------------------------------------------------
# ecs list
# ---------------------------------------------------------------------------


def cmd_ecs_list(args) -> int:
    session = make_boto_session(args.profile, args.region)
    ecs = session.client("ecs")
    cluster = resolve_cluster(args.env, args.cluster)

    print(f"==> Listing ECS tasks in cluster: {cluster}\n")

    task_arns = _ecs_list_task_arns(ecs, cluster=cluster)

    if not task_arns:
        print("No tasks found in cluster.")
        return 0

    tasks = []
    for i in range(0, len(task_arns), 100):
        resp = ecs.describe_tasks(cluster=cluster, tasks=task_arns[i:i+100], include=["TAGS"])
        tasks.extend(resp.get("tasks", []))

    rows = []
    for task in tasks:
        task_id = task["taskArn"].split("/")[-1]
        tags = {t["key"]: t["value"] for t in task.get("tags", [])}
        ip = ""
        for att in task.get("attachments", []):
            if att.get("type") == "ElasticNetworkInterface":
                for detail in att.get("details", []):
                    if detail["name"] == "privateIPv4Address":
                        ip = detail["value"]
        rows.append([
            task_id,
            task.get("lastStatus", ""),
            task.get("desiredStatus", ""),
            tags.get("container_id", ""),
            tags.get("user_id", ""),
            ip,
            task.get("startedAt", ""),
        ])

    headers = ["Task ID", "Status", "Desired", "Container ID", "User ID", "IP Address", "Started At"]
    print(tabulate(rows, headers=headers, tablefmt="grid"))

    running = sum(1 for t in tasks if t.get("desiredStatus") == "RUNNING")
    stopped = sum(1 for t in tasks if t.get("desiredStatus") == "STOPPED")
    print(f"\n==> Task count: RUNNING={running} STOPPED={stopped}")
    return 0


# ---------------------------------------------------------------------------
# ecs stop-all
# ---------------------------------------------------------------------------


def cmd_ecs_stop_all(args) -> int:
    session = make_boto_session(args.profile, args.region)
    ecs = session.client("ecs")
    dynamodb = session.client("dynamodb")
    cluster = resolve_cluster(args.env, args.cluster)
    table = resolve_table(args.env)

    print(f"Cluster:          {cluster}")
    print(f"Cleanup DynamoDB: {args.cleanup_db}")
    print(f"Dry Run:          {args.dry_run}")
    print("-" * 60)

    task_arns = _ecs_list_task_arns(ecs, cluster=cluster, desiredStatus="RUNNING")

    if not task_arns:
        print("No running tasks found.")
        return 0

    print(f"Found {len(task_arns)} running task(s)\n")

    tasks = []
    for i in range(0, len(task_arns), 100):
        resp = ecs.describe_tasks(cluster=cluster, tasks=task_arns[i:i+100], include=["TAGS"])
        tasks.extend(resp.get("tasks", []))

    stopped_count = 0
    db_deleted_count = 0
    db_eligible_count = 0

    for task in tasks:
        task_arn = task["taskArn"]
        task_id = task_arn.split("/")[-1]
        tags = {t["key"]: t["value"] for t in task.get("tags", [])}
        container_id = tags.get("container_id")
        user_id = tags.get("user_id")
        has_db_record = bool(container_id and user_id)

        if has_db_record:
            db_eligible_count += 1

        print(f"Task: {task_id}")
        print(f"  Container ID: {container_id or 'N/A'}")
        print(f"  User ID:      {user_id or 'N/A'}")
        print(f"  Status:       {task.get('lastStatus', 'UNKNOWN')}")

        if args.dry_run:
            print(f"  [DRY RUN] Would stop this task")
            if args.cleanup_db and has_db_record:
                print(f"  [DRY RUN] Would delete DynamoDB record")
        else:
            try:
                ecs.stop_task(cluster=cluster, task=task_arn, reason="Manually stopped via manage.py ecs stop-all")
                print(f"  Stopped task")
                stopped_count += 1
            except ClientError as e:
                print(f"  Error stopping task: {e}")

            if args.cleanup_db and has_db_record:
                try:
                    dynamodb.delete_item(
                        TableName=table,
                        Key={"pk": {"S": f"USER#{user_id}"}, "sk": {"S": f"CONTAINER#{container_id}"}},
                    )
                    print(f"  Deleted DynamoDB record")
                    db_deleted_count += 1
                except Exception as e:
                    print(f"  Failed to delete DynamoDB record: {e}")
        print()

    print("-" * 60)
    if args.dry_run:
        print(f"[DRY RUN] Would stop {len(tasks)} task(s)")
        if args.cleanup_db:
            print(f"[DRY RUN] Would delete {db_eligible_count} DynamoDB record(s)")
    else:
        print(f"Stopped {stopped_count}/{len(tasks)} task(s)")
        if args.cleanup_db:
            print(f"Deleted {db_deleted_count} DynamoDB record(s)")

    return 0


# ---------------------------------------------------------------------------
# ecs cleanup
# ---------------------------------------------------------------------------


def _get_containers_by_status(dynamodb, table: str, *statuses: str) -> list:
    if len(statuses) == 1:
        filter_expr = "#s = :s0"
        expr_values = {":s0": {"S": statuses[0]}}
    else:
        placeholders = ", ".join(f":s{i}" for i in range(len(statuses)))
        filter_expr = f"#s IN ({placeholders})"
        expr_values = {f":s{i}": {"S": s} for i, s in enumerate(statuses)}

    kwargs: dict = {
        "TableName": table,
        "FilterExpression": f"{filter_expr} AND begins_with(sk, :sk_prefix)",
        "ExpressionAttributeNames": {"#s": "status"},
        "ExpressionAttributeValues": {**expr_values, ":sk_prefix": {"S": "CONTAINER#"}},
    }
    return [_parse_container_item(item) for item in _dynamo_paginate(dynamodb.scan, **kwargs)]


def cmd_ecs_cleanup(args) -> int:
    session = make_boto_session(args.profile, args.region)
    dynamodb = session.client("dynamodb")
    ecs = session.client("ecs")
    cluster = resolve_cluster(args.env, args.cluster)
    table = resolve_table(args.env)

    print(f"==> Cleaning up PENDING and FAILED containers")
    print(f"    Table:   {table}")
    print(f"    Cluster: {cluster}\n")

    all_containers = _get_containers_by_status(dynamodb, table, "PENDING", "FAILED")
    pending = sum(1 for c in all_containers if c["status"] == "PENDING")
    failed = sum(1 for c in all_containers if c["status"] == "FAILED")
    print(f"Found {pending} PENDING containers")
    print(f"Found {failed} FAILED containers")

    if not all_containers:
        print("\nNo pending or failed containers found.")
        return 0

    print(f"\n{'='*60}")
    print(f"Total to clean up: {len(all_containers)}")
    print(f"{'='*60}\n")

    if args.dry_run:
        print("DRY RUN — no changes will be made\n")

    for c in all_containers:
        print(f"Container: {c['container_id']}")
        print(f"  User:    {c['user_id']}")
        print(f"  Status:  {c['status']}")
        print(f"  Created: {c['created_at']}")

        if args.dry_run:
            if c["task_arn"]:
                print(f"  [DRY RUN] Would stop ECS task: {c['task_arn']}")
            print(f"  [DRY RUN] Would delete DynamoDB record")
        else:
            if _has_task_arn(c["task_arn"]):
                try:
                    ecs.stop_task(cluster=cluster, task=c["task_arn"], reason="Cleanup: removing pending/failed tasks")
                    print(f"  Stopped ECS task")
                except ecs.exceptions.InvalidParameterException:
                    print(f"  ECS task not found or already stopped")
                except Exception as e:
                    print(f"  Error stopping ECS task: {e}")

            try:
                dynamodb.delete_item(TableName=table, Key={"pk": {"S": c["pk"]}, "sk": {"S": c["sk"]}})
                print(f"  Deleted from DynamoDB")
            except Exception as e:
                print(f"  Error deleting from DynamoDB: {e}")
        print()

    print("=" * 60)
    if args.dry_run:
        print(f"DRY RUN COMPLETE — would have cleaned up {len(all_containers)} containers")
    else:
        print(f"CLEANUP COMPLETE — removed {len(all_containers)} containers")
    print("=" * 60)
    return 0


# ---------------------------------------------------------------------------
# config load
# ---------------------------------------------------------------------------


def cmd_config_load(args) -> int:
    if args.endpoint:
        dynamodb = boto3.client(
            "dynamodb",
            endpoint_url=args.endpoint,
            region_name=args.region,
            aws_access_key_id="local",
            aws_secret_access_key="local",
        )
    else:
        dynamodb = boto3.client("dynamodb", region_name=args.region)

    print("=" * 60)
    print("DynamoDB Configuration Loader")
    print("=" * 60)
    print(f"Table:  {args.table}")
    print(f"Region: {args.region}")
    if args.endpoint:
        print(f"Endpoint: {args.endpoint}")

    if args.verify:
        _config_verify(dynamodb, args.table, args.user_id, args.config_name)
        return 0

    if not args.system and not args.user_id:
        print("\nError: Must specify --system, --user-id, or --verify")
        return 1

    success = True

    if args.system:
        print("\n[System Config] Loading system defaults...")
        item = {
            "pk": {"S": "SYSTEM"},
            "sk": {"S": "CONFIG#defaults"},
            "config_type": {"S": "system_config"},
            "auth_gateway_url": {"S": args.auth_gateway_url},
            "openclaw_url": {"S": args.openclaw_url},
            "openclaw_token": {"S": args.openclaw_token},
            "voice_gateway_url": {"S": args.voice_gateway_url},
            "updated_at": {"S": datetime.now(timezone.utc).isoformat()},
        }
        try:
            dynamodb.put_item(TableName=args.table, Item=item)
            print("  System defaults loaded")
            print(f"  auth_gateway_url: {args.auth_gateway_url}")
            print(f"  openclaw_url:     {args.openclaw_url}")
            print(f"  voice_gateway_url: {args.voice_gateway_url}")
        except ClientError as e:
            print(f"  Failed: {e}")
            success = False

    if args.user_id:
        print(f"\n[User Config] Loading user defaults for {args.user_id}...")
        item = {
            "pk": {"S": f"USER#{args.user_id}"},
            "sk": {"S": f"CONFIG#{args.config_name}"},
            "config_type": {"S": "user_config"},
            "user_id": {"S": args.user_id},
            "llm_provider": {"S": args.llm_provider},
            "openclaw_model": {"S": args.openclaw_model},
            "created_at": {"S": datetime.now(timezone.utc).isoformat()},
            "updated_at": {"S": datetime.now(timezone.utc).isoformat()},
        }
        for key, flag in [
            ("auth_gateway_api_key", args.auth_gateway_api_key),
            ("anthropic_api_key", args.anthropic_api_key),
            ("openai_api_key", args.openai_api_key),
            ("openrouter_api_key", args.openrouter_api_key),
        ]:
            if flag:
                item[key] = {"S": flag}
                print(f"  {key}: {flag[:20]}...")
        try:
            dynamodb.put_item(TableName=args.table, Item=item)
            print("  User defaults loaded")
        except ClientError as e:
            print(f"  Failed: {e}")
            success = False

    print("\n" + "=" * 60)
    _config_verify(dynamodb, args.table, args.user_id, args.config_name)
    print("\n" + "=" * 60)
    if success:
        print("Configuration loaded successfully!")
    else:
        print("Some configurations failed to load")
        return 1
    return 0


def _config_verify(dynamodb, table_name: str, user_id: Optional[str], config_name: str) -> None:
    print("\n[Verification] Checking existing configurations...\n")

    print("System Config:")
    try:
        response = dynamodb.get_item(
            TableName=table_name,
            Key={"pk": {"S": "SYSTEM"}, "sk": {"S": "CONFIG#defaults"}},
        )
        if "Item" in response:
            item = response["Item"]
            print("  System config exists")
            for field in ["auth_gateway_url", "openclaw_url", "openclaw_token", "voice_gateway_url", "updated_at"]:
                print(f"  {field}: {item.get(field, {}).get('S', 'N/A')}")
        else:
            print("  System config not found")
    except ClientError as e:
        print(f"  Error: {e}")

    if user_id:
        print(f"\nUser Config for {user_id}:")
        try:
            response = dynamodb.get_item(
                TableName=table_name,
                Key={"pk": {"S": f"USER#{user_id}"}, "sk": {"S": f"CONFIG#{config_name}"}},
            )
            if "Item" in response:
                item = response["Item"]
                print("  User config exists")
                for field in ["user_id", "llm_provider", "openclaw_model", "created_at", "updated_at"]:
                    print(f"  {field}: {item.get(field, {}).get('S', 'N/A')}")
                for key_field in ["auth_gateway_api_key", "anthropic_api_key", "openai_api_key"]:
                    if key_field in item:
                        val = item[key_field]["S"]
                        print(f"  {key_field}: {val[:20]}..." if len(val) > 20 else f"  {key_field}: {val}")
            else:
                print("  User config not found")
        except ClientError as e:
            print(f"  Error: {e}")


# ---------------------------------------------------------------------------
# config setup-test
# ---------------------------------------------------------------------------


def cmd_config_setup_test(args) -> int:
    if not any([args.anthropic_key, args.openai_key, args.openrouter_key]):
        print("Error: At least one API key is required (--anthropic-key, --openai-key, or --openrouter-key)")
        return 1

    dynamodb = boto3.resource(
        "dynamodb",
        endpoint_url=args.endpoint,
        region_name=args.region,
        aws_access_key_id="local",
        aws_secret_access_key="local",
    )
    table = dynamodb.Table(args.table)

    print(f"Setting up test config in DynamoDB table: {args.table}")
    print(f"Endpoint: {args.endpoint}")
    print(f"User ID:  {args.user_id}\n")

    if args.anthropic_key:
        llm_provider = "anthropic"
    elif args.openai_key:
        llm_provider = "openai"
    else:
        llm_provider = "openrouter"

    print("[1/2] Creating system config...")
    system_config = {
        "pk": "SYSTEM",
        "sk": "CONFIG#defaults",
        "config_type": "system_config",
        "auth_gateway_url": "http://host.docker.internal:8001",
        "openclaw_url": "http://localhost:18789",
        "openclaw_token": "test-token-123",
        "voice_gateway_url": "ws://localhost:9090",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    table.put_item(Item=system_config)
    print("  System config created")

    print("\n[2/2] Creating user config...")
    user_config: dict = {
        "pk": f"USER#{args.user_id}",
        "sk": "CONFIG#primary",
        "config_type": "user_config",
        "user_id": args.user_id,
        "llm_provider": llm_provider,
        "openclaw_model": "claude-3-haiku-20240307",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    for key, val in [
        ("anthropic_api_key", args.anthropic_key),
        ("openai_api_key", args.openai_key),
        ("openrouter_api_key", args.openrouter_key),
    ]:
        if val:
            user_config[key] = val
            print(f"  {key}: {val[:20]}...")

    auth_api_key = f"{args.user_id}:test-token-xyz-789"
    user_config["auth_gateway_api_key"] = auth_api_key
    print(f"  auth_gateway_api_key: {auth_api_key}")

    table.put_item(Item=user_config)
    print("  User config created")
    print(f"\nTest config setup complete.")
    print(f"\nNext steps:")
    print(f"  manage.py containers launch --user-id {args.user_id} --token test-token-xyz-789 --local")
    return 0


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


def cmd_verify(args) -> int:
    import os

    print(f"\n{'=' * 80}")
    print(f"AWS Configuration Verification")
    print(f"{'=' * 80}")

    results = []
    session = make_boto_session(args.profile, args.region)

    # AWS credentials
    print(f"\nChecking: AWS Credentials")
    try:
        sts = session.client("sts")
        identity = sts.get_caller_identity()
        print(f"  OK — Account: {identity['Account']}, ARN: {identity['Arn']}")
        results.append(True)
    except Exception as e:
        print(f"  FAILED — {e}")
        results.append(False)

    # Auth gateway
    auth_url = os.getenv("AUTH_GATEWAY_URL", "https://z1fm1cdkph.execute-api.ap-southeast-2.amazonaws.com")
    print(f"\nChecking: Auth Gateway ({auth_url})")
    try:
        response = requests.get(f"{auth_url}/health", timeout=10)
        response.raise_for_status()
        print(f"  OK")
        results.append(True)
    except Exception as e:
        print(f"  FAILED — {e}")
        results.append(False)

    # Orchestrator
    orchestrator_url = os.getenv("ORCHESTRATOR_URL", "https://prz6mum7c7.execute-api.ap-southeast-2.amazonaws.com")
    print(f"\nChecking: Orchestrator ({orchestrator_url})")
    try:
        response = requests.get(f"{orchestrator_url}/health", timeout=10)
        response.raise_for_status()
        print(f"  OK")
        results.append(True)
    except Exception as e:
        print(f"  FAILED — {e}")
        results.append(False)

    # DynamoDB
    table_name = os.getenv("CONTAINERS_TABLE", "openclaw-containers")
    print(f"\nChecking: DynamoDB Table ({table_name})")
    try:
        dynamodb = session.client("dynamodb")
        resp = dynamodb.describe_table(TableName=table_name)
        table_info = resp["Table"]
        print(f"  OK — Status: {table_info['TableStatus']}, Items: {table_info.get('ItemCount', '?')}")
        results.append(True)
    except Exception as e:
        print(f"  FAILED — {e}")
        results.append(False)

    # ECS cluster
    cluster_name = os.getenv("ECS_CLUSTER_NAME", "clawtalk-dev")
    print(f"\nChecking: ECS Cluster ({cluster_name})")
    try:
        ecs = session.client("ecs")
        resp = ecs.describe_clusters(clusters=[cluster_name])
        clusters = resp.get("clusters", [])
        if not clusters:
            raise Exception(f"Cluster '{cluster_name}' not found")
        cluster = clusters[0]
        print(f"  OK — Status: {cluster['status']}, Running: {cluster.get('runningTasksCount', 0)}")
        results.append(True)
    except Exception as e:
        print(f"  FAILED — {e}")
        results.append(False)

    passed = sum(results)
    total = len(results)
    print(f"\n{'=' * 80}")
    if passed == total:
        print(f"All checks passed ({passed}/{total})")
        print(f"\nReady to run end-to-end tests:")
        print(f"  E2E_TESTS=1 pytest tests/e2e/")
        return 0
    else:
        print(f"Some checks failed ({passed}/{total} passed)")
        print(f"\nFix the issues above before running tests.")
        return 1


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="manage.py",
        description="Clawtalk orchestrator management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    groups = parser.add_subparsers(dest="group", metavar="GROUP")
    groups.required = True

    # -----------------------------------------------------------------------
    # containers
    # -----------------------------------------------------------------------
    c = groups.add_parser(
        "containers",
        help="Container lifecycle management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Manage openclaw-agent containers.\n\nCommands: list, launch, delete, inspect, logs, exec",
    )
    c_sub = c.add_subparsers(dest="command", metavar="COMMAND")
    c_sub.required = True

    # containers list
    p = c_sub.add_parser("list", help="List containers from DynamoDB")
    add_common(p)
    p.add_argument("--user-id", help="Filter by specific user ID")
    p.set_defaults(func=cmd_containers_list)

    # containers launch
    p = c_sub.add_parser(
        "launch",
        help="Launch a new container via the orchestrator API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Launch a new openclaw-agent container.\n\n"
            "Examples:\n"
            "  manage.py containers launch --user-id USER --token TOKEN\n"
            "  manage.py containers launch --user-id USER --token TOKEN --wait\n"
            "  manage.py containers launch --user-id USER --token TOKEN --local\n"
            "  manage.py containers launch --user-id USER --token TOKEN --config '{\"memory\": 512}'"
        ),
    )
    add_common(p)
    p.add_argument("--user-id", required=True, help="User ID for authentication")
    p.add_argument("--token", required=True, help="Authentication token")
    p.add_argument("--name", help="Optional container name")
    p.add_argument("--config", help="Optional config as JSON string")
    p.add_argument("--local", action="store_true", help="Use local dev URL (localhost:8000)")
    p.add_argument("--url", help="Custom base URL (overrides --env and --local)")
    p.add_argument("--wait", action="store_true", help="Wait for container to become healthy")
    p.add_argument("--wait-timeout", type=int, default=300, metavar="SECONDS",
                   help="Health check timeout in seconds (default: 300)")
    p.set_defaults(func=cmd_containers_launch)

    # containers delete
    p = c_sub.add_parser(
        "delete",
        help="Delete one or more containers (stops ECS task and removes DynamoDB record)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Delete containers by ID, all for a user, or by status.\n\n"
            "Examples:\n"
            "  manage.py containers delete oc-abc123 --user-id USER\n"
            "  manage.py containers delete oc-abc oc-def --user-id USER --dry-run\n"
            "  manage.py containers delete --all --user-id USER\n"
            "  manage.py containers delete --all  (system-wide)\n"
            "  manage.py containers delete --status STOPPED"
        ),
    )
    add_common(p)
    p.add_argument("container_ids", nargs="*", metavar="CONTAINER_ID",
                   help="One or more container IDs to delete")
    p.add_argument("--user-id", help="User ID who owns the containers")
    p.add_argument("--all", action="store_true",
                   help="Delete all containers (optionally filtered by --user-id)")
    p.add_argument("--status", metavar="STATUS",
                   help="Delete containers with specific status (e.g. STOPPED, FAILED)")
    p.add_argument("--dry-run", action="store_true",
                   help="Show what would be deleted without deleting")
    p.add_argument("--yes", "-y", action="store_true",
                   help="Skip confirmation prompt")
    p.set_defaults(func=cmd_containers_delete)

    # containers inspect
    p = c_sub.add_parser(
        "inspect",
        help="Inspect container/agent status (DynamoDB + ECS task + optional logs)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Inspect an agent by container ID or full UUID.\n\n"
            "Examples:\n"
            "  manage.py containers inspect oc-abc12345\n"
            "  manage.py containers inspect e20ac9f1-2d3a-462c-9a37-205779ac0e0a\n"
            "  manage.py containers inspect oc-abc12345 --logs --since 60\n"
            "  manage.py containers inspect oc-abc12345 --env prod"
        ),
    )
    add_common(p)
    p.add_argument("agent_id", metavar="AGENT_ID",
                   help="Agent/container ID (UUID or oc- format)")
    p.add_argument("--logs", action="store_true", help="Fetch CloudWatch logs")
    p.add_argument("--since", type=int, default=60, metavar="MINUTES",
                   help="Search logs from last N minutes (default: 60)")
    p.set_defaults(func=cmd_containers_inspect)

    # containers logs
    p = c_sub.add_parser(
        "logs",
        help="Fetch CloudWatch logs for a container",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Fetch or follow CloudWatch logs for a container.\n\n"
            "Examples:\n"
            "  manage.py containers logs oc-abc123 --user-id USER\n"
            "  manage.py containers logs oc-abc123 --user-id USER --follow\n"
            "  manage.py containers logs --task-id abc123def456\n"
            "  manage.py containers logs oc-abc123 --user-id USER --since 60"
        ),
    )
    add_common(p)
    p.add_argument("container_id", nargs="?", metavar="CONTAINER_ID",
                   help="Container ID (e.g. oc-abc12345)")
    p.add_argument("--user-id", help="User ID who owns the container")
    p.add_argument("--task-id", metavar="TASK_ID",
                   help="ECS task ID to fetch logs for (alternative to CONTAINER_ID)")
    p.add_argument("--follow", "-f", action="store_true", help="Follow logs in real-time")
    p.add_argument("--since", type=int, default=30, metavar="MINUTES",
                   help="Show logs from last N minutes (default: 30)")
    p.set_defaults(func=cmd_containers_logs)

    # containers exec
    p = c_sub.add_parser(
        "exec",
        help="Open an interactive shell on a running container via ECS exec",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Open an interactive shell on a running container.\n\n"
            "Prerequisites:\n"
            "  - ECS exec must be enabled on the task (enableExecuteCommand: true)\n"
            "  - AWS Session Manager plugin must be installed\n\n"
            "Examples:\n"
            "  manage.py containers exec oc-abc123 --user-id USER\n"
            "  manage.py containers exec --task-arn arn:aws:ecs:...\n"
            "  manage.py containers exec oc-abc123 --user-id USER --command /bin/sh"
        ),
    )
    add_common(p)
    p.add_argument("container_id", nargs="?", metavar="CONTAINER_ID",
                   help="Container ID (e.g. oc-abc12345)")
    p.add_argument("--user-id", help="User ID who owns the container")
    p.add_argument("--task-arn", metavar="TASK_ARN",
                   help="Task ARN to connect to (alternative to CONTAINER_ID + --user-id)")
    p.add_argument("--container", default="openclaw-agent", metavar="NAME",
                   help="Container name within the task (default: openclaw-agent)")
    p.add_argument("--command", default="/bin/bash", metavar="CMD",
                   help="Command to execute (default: /bin/bash)")
    p.set_defaults(func=cmd_containers_exec)

    # -----------------------------------------------------------------------
    # ecs
    # -----------------------------------------------------------------------
    e = groups.add_parser(
        "ecs",
        help="ECS task management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Manage ECS tasks directly.\n\nCommands: list, stop-all, cleanup",
    )
    e_sub = e.add_subparsers(dest="command", metavar="COMMAND")
    e_sub.required = True

    # ecs list
    p = e_sub.add_parser("list", help="List all ECS tasks in the cluster")
    add_common(p)
    p.set_defaults(func=cmd_ecs_list)

    # ecs stop-all
    p = e_sub.add_parser("stop-all", help="Stop all running ECS tasks")
    add_common(p)
    p.add_argument("--cleanup-db", action="store_true",
                   help="Also delete container records from DynamoDB")
    p.add_argument("--dry-run", action="store_true",
                   help="Show what would happen without making changes")
    p.set_defaults(func=cmd_ecs_stop_all)

    # ecs cleanup
    p = e_sub.add_parser("cleanup", help="Remove PENDING and FAILED tasks from ECS and DynamoDB")
    add_common(p)
    p.add_argument("--dry-run", action="store_true",
                   help="Show what would happen without making changes")
    p.set_defaults(func=cmd_ecs_cleanup)

    # -----------------------------------------------------------------------
    # config
    # -----------------------------------------------------------------------
    cfg = groups.add_parser(
        "config",
        help="DynamoDB configuration management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Load or inspect configuration in DynamoDB.\n\nCommands: load, setup-test",
    )
    cfg_sub = cfg.add_subparsers(dest="command", metavar="COMMAND")
    cfg_sub.required = True

    # config load
    p = cfg_sub.add_parser(
        "load",
        help="Load system or user defaults into DynamoDB",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Load default configuration into DynamoDB.\n\n"
            "Examples:\n"
            "  manage.py config load --system\n"
            "  manage.py config load --system --auth-gateway-url https://...\n"
            "  manage.py config load --user-id abc123 --anthropic-api-key sk-ant-...\n"
            "  manage.py config load --verify\n"
            "  manage.py config load --verify --user-id abc123"
        ),
    )
    p.add_argument("--system", action="store_true", help="Load system defaults")
    p.add_argument("--user-id", metavar="USER_ID", help="Load user defaults for this user ID")
    p.add_argument("--verify", action="store_true",
                   help="Verify existing configurations without loading")
    # DynamoDB connection
    p.add_argument("--endpoint", metavar="URL",
                   help="DynamoDB endpoint URL (for local development)")
    p.add_argument("--region", default="ap-southeast-2", metavar="REGION",
                   help="AWS region (default: ap-southeast-2)")
    p.add_argument("--table", default="openclaw-containers", metavar="TABLE",
                   help="DynamoDB table name (default: openclaw-containers)")
    # System config values
    p.add_argument("--auth-gateway-url",
                   default="https://z1fm1cdkph.execute-api.ap-southeast-2.amazonaws.com",
                   metavar="URL", help="Auth gateway URL")
    p.add_argument("--openclaw-url", default="http://localhost:18789",
                   metavar="URL", help="OpenClaw URL")
    p.add_argument("--openclaw-token", default="test-token-123",
                   metavar="TOKEN", help="OpenClaw token")
    p.add_argument("--voice-gateway-url",
                   default="http://voice-gateway-dev-59337216.ap-southeast-2.elb.amazonaws.com",
                   metavar="URL", help="Voice gateway URL")
    # User config values
    p.add_argument("--config-name", default="default", metavar="NAME",
                   help="Config name (default: default)")
    p.add_argument("--llm-provider", default="anthropic", metavar="PROVIDER",
                   help="LLM provider (default: anthropic)")
    p.add_argument("--openclaw-model", default="claude-3-haiku-20240307",
                   metavar="MODEL", help="OpenClaw model (default: claude-3-haiku-20240307)")
    p.add_argument("--auth-gateway-api-key", metavar="KEY", help="Auth gateway API key")
    p.add_argument("--anthropic-api-key", metavar="KEY", help="Anthropic API key")
    p.add_argument("--openai-api-key", metavar="KEY", help="OpenAI API key")
    p.add_argument("--openrouter-api-key", metavar="KEY", help="OpenRouter API key")
    p.set_defaults(func=cmd_config_load)

    # config setup-test
    p = cfg_sub.add_parser(
        "setup-test",
        help="Bootstrap local test config in DynamoDB for local development",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Create test system and user configuration in a local DynamoDB instance.\n\n"
            "Examples:\n"
            "  manage.py config setup-test --user-id test-user --anthropic-key sk-ant-...\n"
            "  manage.py config setup-test --user-id test-user --openai-key sk-..."
        ),
    )
    p.add_argument("--user-id", required=True, metavar="USER_ID",
                   help="User ID (e.g. test-user-123)")
    p.add_argument("--anthropic-key", metavar="KEY", help="Anthropic API key")
    p.add_argument("--openai-key", metavar="KEY", help="OpenAI API key")
    p.add_argument("--openrouter-key", metavar="KEY", help="OpenRouter API key")
    p.add_argument("--endpoint", default="http://localhost:8000", metavar="URL",
                   help="DynamoDB endpoint (default: http://localhost:8000)")
    p.add_argument("--region", default="ap-southeast-2", metavar="REGION",
                   help="AWS region (default: ap-southeast-2)")
    p.add_argument("--table", default="openclaw-containers", metavar="TABLE",
                   help="DynamoDB table name (default: openclaw-containers)")
    p.set_defaults(func=cmd_config_setup_test)

    # -----------------------------------------------------------------------
    # verify
    # -----------------------------------------------------------------------
    p = groups.add_parser(
        "verify",
        help="Verify AWS credentials and service connectivity",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Verify AWS configuration before running tests.\n\n"
            "Checks:\n"
            "  1. AWS credentials are configured\n"
            "  2. Auth gateway is accessible\n"
            "  3. Orchestrator is accessible\n"
            "  4. DynamoDB table exists\n"
            "  5. ECS cluster exists\n\n"
            "Example:\n"
            "  manage.py verify\n"
            "  manage.py verify --profile prod --region us-east-1"
        ),
    )
    p.add_argument("--profile", default="personal", metavar="PROFILE",
                   help="AWS profile name (default: personal)")
    p.add_argument("--region", default="ap-southeast-2", metavar="REGION",
                   help="AWS region (default: ap-southeast-2)")
    p.set_defaults(func=cmd_verify)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except Exception as e:
        print(f"ERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
