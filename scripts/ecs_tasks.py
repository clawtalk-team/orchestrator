#!/usr/bin/env python3
"""
Manage ECS tasks for openclaw-agent.

Subcommands:
  list       List all tasks in the cluster (default)
  stop-all   Stop all running tasks, optionally remove DynamoDB records
  cleanup    Remove PENDING and FAILED tasks from ECS and DynamoDB

Usage:
  python scripts/ecs_tasks.py list
  python scripts/ecs_tasks.py stop-all --dry-run
  python scripts/ecs_tasks.py stop-all --cleanup-db
  python scripts/ecs_tasks.py cleanup --dry-run
  python scripts/ecs_tasks.py cleanup --env prod

Common options (all subcommands):
  --env       Environment (dev/prod), default: dev
  --cluster   ECS cluster name (overrides env default)
  --profile   AWS profile, default: personal
  --region    AWS region, default: ap-southeast-2
"""

import argparse
import sys

import boto3
from botocore.exceptions import ClientError
from tabulate import tabulate


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def make_session(profile: str, region: str) -> boto3.Session:
    return boto3.Session(profile_name=profile, region_name=region)


def resolve_cluster(args) -> str:
    return args.cluster or f"clawtalk-{args.env}"


def resolve_table(args) -> str:
    return f"openclaw-containers-{args.env}"


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def cmd_list(args) -> int:
    session = make_session(args.profile, args.region)
    ecs = session.client("ecs")
    cluster = resolve_cluster(args)

    print(f"==> Listing ECS tasks in cluster: {cluster}\n")

    task_arns = []
    kwargs: dict = {"cluster": cluster}
    while True:
        response = ecs.list_tasks(**kwargs)
        task_arns.extend(response.get("taskArns", []))
        if "nextToken" not in response:
            break
        kwargs["nextToken"] = response["nextToken"]

    if not task_arns:
        print("No tasks found in cluster.")
        return 0

    tasks = []
    for i in range(0, len(task_arns), 100):
        chunk = task_arns[i : i + 100]
        resp = ecs.describe_tasks(cluster=cluster, tasks=chunk, include=["TAGS"])
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

    running_count = sum(1 for t in tasks if t.get("desiredStatus") == "RUNNING")
    stopped_count = sum(1 for t in tasks if t.get("desiredStatus") == "STOPPED")
    print(f"\n==> Task count by status:")
    print(f"  RUNNING: {running_count}")
    print(f"  STOPPED: {stopped_count}")
    return 0


# ---------------------------------------------------------------------------
# stop-all
# ---------------------------------------------------------------------------


def _stop_task(ecs, cluster: str, task_arn: str, reason: str) -> bool:
    try:
        ecs.stop_task(cluster=cluster, task=task_arn, reason=reason)
        return True
    except ClientError as e:
        print(f"  Error stopping task {task_arn}: {e}")
        return False


def _delete_container_record(dynamodb, table: str, user_id: str, container_id: str) -> bool:
    try:
        dynamodb.delete_item(
            TableName=table,
            Key={
                "pk": {"S": f"USER#{user_id}"},
                "sk": {"S": f"CONTAINER#{container_id}"},
            },
        )
        return True
    except Exception as e:
        print(f"  Error deleting DynamoDB record for {container_id}: {e}")
        return False


def cmd_stop_all(args) -> int:
    session = make_session(args.profile, args.region)
    ecs = session.client("ecs")
    dynamodb = session.client("dynamodb")
    cluster = resolve_cluster(args)
    table = resolve_table(args)

    print(f"Cluster:          {cluster}")
    print(f"Cleanup DynamoDB: {args.cleanup_db}")
    print(f"Dry Run:          {args.dry_run}")
    print("-" * 60)

    task_arns = []
    kwargs: dict = {"cluster": cluster, "desiredStatus": "RUNNING"}
    while True:
        resp = ecs.list_tasks(**kwargs)
        task_arns.extend(resp.get("taskArns", []))
        if "nextToken" not in resp:
            break
        kwargs["nextToken"] = resp["nextToken"]

    if not task_arns:
        print("No running tasks found.")
        return 0

    print(f"Found {len(task_arns)} running task(s)\n")

    tasks = []
    for i in range(0, len(task_arns), 100):
        chunk = task_arns[i : i + 100]
        resp = ecs.describe_tasks(cluster=cluster, tasks=chunk, include=["TAGS"])
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
            if _stop_task(ecs, cluster, task_arn, "Manually stopped via ecs_tasks.py stop-all"):
                print(f"  Stopped task")
                stopped_count += 1
            else:
                print(f"  Failed to stop task")

            if args.cleanup_db and has_db_record:
                if _delete_container_record(dynamodb, table, user_id, container_id):
                    print(f"  Deleted DynamoDB record")
                    db_deleted_count += 1
                else:
                    print(f"  Failed to delete DynamoDB record")
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

    return 0 if (args.dry_run or stopped_count == len(tasks)) else 1


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------


def _get_containers_by_status(dynamodb, table: str, status: str) -> list[dict]:
    kwargs = {
        "TableName": table,
        "FilterExpression": "#s = :status AND begins_with(sk, :sk_prefix)",
        "ExpressionAttributeNames": {"#s": "status"},
        "ExpressionAttributeValues": {
            ":status": {"S": status},
            ":sk_prefix": {"S": "CONTAINER#"},
        },
    }
    items = []
    while True:
        resp = dynamodb.scan(**kwargs)
        for item in resp.get("Items", []):
            items.append({
                "container_id": item.get("container_id", {}).get("S", ""),
                "user_id": item.get("user_id", {}).get("S", ""),
                "task_arn": item.get("task_arn", {}).get("S", ""),
                "status": item.get("status", {}).get("S", ""),
                "pk": item.get("pk", {}).get("S", ""),
                "sk": item.get("sk", {}).get("S", ""),
                "created_at": item.get("created_at", {}).get("S", ""),
            })
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return items


def _stop_ecs_task_if_exists(ecs, cluster: str, task_arn: str) -> bool:
    if not task_arn:
        return False
    try:
        ecs.stop_task(cluster=cluster, task=task_arn, reason="Cleanup: removing pending/failed tasks")
        print(f"  Stopped ECS task: {task_arn}")
        return True
    except ecs.exceptions.InvalidParameterException:
        print(f"  ECS task not found or already stopped: {task_arn}")
        return False
    except Exception as e:
        print(f"  Error stopping ECS task {task_arn}: {e}")
        return False


def _delete_record(dynamodb, table: str, pk: str, sk: str) -> bool:
    try:
        dynamodb.delete_item(TableName=table, Key={"pk": {"S": pk}, "sk": {"S": sk}})
        print(f"  Deleted from DynamoDB")
        return True
    except Exception as e:
        print(f"  Error deleting from DynamoDB: {e}")
        return False


def cmd_cleanup(args) -> int:
    session = make_session(args.profile, args.region)
    dynamodb = session.client("dynamodb")
    ecs = session.client("ecs")
    cluster = resolve_cluster(args)
    table = resolve_table(args)

    print(f"==> Cleaning up PENDING and FAILED containers")
    print(f"    Table:   {table}")
    print(f"    Cluster: {cluster}\n")

    pending = _get_containers_by_status(dynamodb, table, "PENDING")
    print(f"Found {len(pending)} PENDING containers")
    failed = _get_containers_by_status(dynamodb, table, "FAILED")
    print(f"Found {len(failed)} FAILED containers")

    all_containers = pending + failed
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
            print(f"  [DRY RUN] Would delete DynamoDB record (pk={c['pk']}, sk={c['sk']})")
        else:
            if c["task_arn"]:
                _stop_ecs_task_if_exists(ecs, cluster, c["task_arn"])
            _delete_record(dynamodb, table, c["pk"], c["sk"])
        print()

    print("=" * 60)
    if args.dry_run:
        print(f"DRY RUN COMPLETE — would have cleaned up {len(all_containers)} containers")
    else:
        print(f"CLEANUP COMPLETE — removed {len(all_containers)} containers")
    print("=" * 60)
    return 0


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------

COMMON_ARGS = [
    (["--env"], {"default": "dev", "help": "Environment (dev/prod), default: dev"}),
    (["--cluster"], {"default": None, "help": "ECS cluster name (default: clawtalk-{env})"}),
    (["--profile"], {"default": "personal", "help": "AWS profile, default: personal"}),
    (["--region"], {"default": "ap-southeast-2", "help": "AWS region, default: ap-southeast-2"}),
]


def add_common(parser):
    for flags, kwargs in COMMON_ARGS:
        parser.add_argument(*flags, **kwargs)


def main():
    parser = argparse.ArgumentParser(
        description="Manage ECS tasks for openclaw-agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    # list
    p_list = sub.add_parser("list", help="List all tasks in the cluster")
    add_common(p_list)

    # stop-all
    p_stop = sub.add_parser("stop-all", help="Stop all running tasks")
    add_common(p_stop)
    p_stop.add_argument("--cleanup-db", action="store_true",
                        help="Also delete container records from DynamoDB")
    p_stop.add_argument("--dry-run", action="store_true",
                        help="Show what would happen without making changes")

    # cleanup
    p_clean = sub.add_parser("cleanup", help="Remove PENDING and FAILED tasks")
    add_common(p_clean)
    p_clean.add_argument("--dry-run", action="store_true",
                         help="Show what would happen without making changes")

    args = parser.parse_args()

    dispatch = {
        "list": cmd_list,
        "stop-all": cmd_stop_all,
        "cleanup": cmd_cleanup,
    }
    try:
        sys.exit(dispatch[args.command](args))
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
