#!/usr/bin/env python3
"""
Delete all running openclaw-agent ECS tasks.

This script will:
1. List all RUNNING tasks in the ECS cluster
2. Stop each task
3. Optionally clean up DynamoDB records for the stopped containers

Usage:
    python scripts/delete_all_running_tasks.py [--env ENV] [--cluster CLUSTER] [--cleanup-db] [--dry-run]

Examples:
    # Dry run to see what would be deleted
    python scripts/delete_all_running_tasks.py --dry-run

    # Delete all running tasks (keeps DynamoDB records)
    python scripts/delete_all_running_tasks.py

    # Delete all running tasks and cleanup DynamoDB records
    python scripts/delete_all_running_tasks.py --cleanup-db

    # Specify environment
    python scripts/delete_all_running_tasks.py --env prod --cleanup-db
"""

import argparse
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import Settings
from app.services import dynamodb


def get_running_tasks(ecs_client, cluster_name: str):
    """Get all running tasks in the cluster."""
    try:
        # List tasks with RUNNING status
        response = ecs_client.list_tasks(
            cluster=cluster_name,
            desiredStatus="RUNNING"
        )

        return response.get("taskArns", [])
    except ClientError as e:
        print(f"Error listing tasks: {e}")
        return []


def get_task_details(ecs_client, cluster_name: str, task_arns: list):
    """Get detailed information about tasks."""
    if not task_arns:
        return []

    try:
        response = ecs_client.describe_tasks(
            cluster=cluster_name,
            tasks=task_arns
        )
        return response.get("tasks", [])
    except ClientError as e:
        print(f"Error describing tasks: {e}")
        return []


def extract_container_info(task):
    """Extract container_id and user_id from task tags."""
    tags = task.get("tags", [])
    container_id = None
    user_id = None

    for tag in tags:
        if tag["key"] == "container_id":
            container_id = tag["value"]
        elif tag["key"] == "user_id":
            user_id = tag["value"]

    return container_id, user_id


def stop_task(ecs_client, cluster_name: str, task_arn: str, reason: str = "Manually stopped via delete_all_running_tasks.py"):
    """Stop an ECS task."""
    try:
        response = ecs_client.stop_task(
            cluster=cluster_name,
            task=task_arn,
            reason=reason
        )
        return True
    except ClientError as e:
        print(f"Error stopping task {task_arn}: {e}")
        return False


def delete_container_record(user_id: str, container_id: str):
    """Delete container record from DynamoDB."""
    try:
        dynamodb.delete_container(user_id, container_id)
        return True
    except Exception as e:
        print(f"Error deleting DynamoDB record for {container_id}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Delete all running openclaw-agent ECS tasks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        "--env",
        default="dev",
        help="Environment (dev, staging, prod). Default: dev"
    )
    parser.add_argument(
        "--cluster",
        help="ECS cluster name (overrides env-based default)"
    )
    parser.add_argument(
        "--cleanup-db",
        action="store_true",
        help="Also delete container records from DynamoDB"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting"
    )
    parser.add_argument(
        "--profile",
        default="personal",
        help="AWS profile to use. Default: personal"
    )
    parser.add_argument(
        "--region",
        default="ap-southeast-2",
        help="AWS region. Default: ap-southeast-2"
    )

    args = parser.parse_args()

    # Initialize settings
    settings = Settings()
    cluster_name = args.cluster or settings.ecs_cluster_name

    print(f"Environment: {args.env}")
    print(f"ECS Cluster: {cluster_name}")
    print(f"AWS Profile: {args.profile}")
    print(f"AWS Region: {args.region}")
    print(f"Cleanup DynamoDB: {args.cleanup_db}")
    print(f"Dry Run: {args.dry_run}")
    print("-" * 60)

    # Initialize AWS session and clients
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    ecs_client = session.client("ecs")

    # Get all running tasks
    print("Fetching running tasks...")
    task_arns = get_running_tasks(ecs_client, cluster_name)

    if not task_arns:
        print("No running tasks found.")
        return 0

    print(f"Found {len(task_arns)} running task(s)")
    print()

    # Get task details
    tasks = get_task_details(ecs_client, cluster_name, task_arns)

    # Process each task
    stopped_count = 0
    db_deleted_count = 0

    for task in tasks:
        task_arn = task["taskArn"]
        task_id = task_arn.split("/")[-1]
        container_id, user_id = extract_container_info(task)

        print(f"Task: {task_id}")
        print(f"  ARN: {task_arn}")
        print(f"  Container ID: {container_id or 'N/A'}")
        print(f"  User ID: {user_id or 'N/A'}")
        print(f"  Status: {task.get('lastStatus', 'UNKNOWN')}")

        if args.dry_run:
            print(f"  [DRY RUN] Would stop this task")
            if args.cleanup_db and container_id and user_id:
                print(f"  [DRY RUN] Would delete DynamoDB record")
        else:
            # Stop the task
            if stop_task(ecs_client, cluster_name, task_arn):
                print(f"  ✓ Stopped task")
                stopped_count += 1
            else:
                print(f"  ✗ Failed to stop task")

            # Delete DynamoDB record if requested
            if args.cleanup_db and container_id and user_id:
                if delete_container_record(user_id, container_id):
                    print(f"  ✓ Deleted DynamoDB record")
                    db_deleted_count += 1
                else:
                    print(f"  ✗ Failed to delete DynamoDB record")

        print()

    # Summary
    print("-" * 60)
    if args.dry_run:
        print(f"[DRY RUN] Would stop {len(tasks)} task(s)")
        if args.cleanup_db:
            valid_records = sum(1 for t in tasks if extract_container_info(t)[0] and extract_container_info(t)[1])
            print(f"[DRY RUN] Would delete {valid_records} DynamoDB record(s)")
    else:
        print(f"Successfully stopped {stopped_count}/{len(tasks)} task(s)")
        if args.cleanup_db:
            print(f"Deleted {db_deleted_count} DynamoDB record(s)")

    return 0 if stopped_count == len(tasks) or args.dry_run else 1


if __name__ == "__main__":
    sys.exit(main())
