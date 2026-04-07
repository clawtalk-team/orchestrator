#!/usr/bin/env python3
"""
Cleanup script to remove pending and failed tasks from ECS and DynamoDB.

This script:
1. Scans DynamoDB for all containers with PENDING or FAILED status
2. Stops any associated ECS tasks (if they exist)
3. Deletes the container records from DynamoDB

Usage: python scripts/cleanup_tasks.py [--env ENV] [--dry-run]
"""

import boto3
from datetime import datetime


def get_containers_by_status(dynamodb_client, table_name: str, status: str):
    """Get all containers with a specific status."""
    scan_kwargs = {
        "TableName": table_name,
        "FilterExpression": "#s = :status AND begins_with(sk, :sk_prefix)",
        "ExpressionAttributeNames": {"#s": "status"},
        "ExpressionAttributeValues": {
            ":status": {"S": status},
            ":sk_prefix": {"S": "CONTAINER#"},
        },
    }

    containers = []
    while True:
        response = dynamodb_client.scan(**scan_kwargs)
        items = response.get("Items", [])

        for item in items:
            containers.append({
                "container_id": item.get("container_id", {}).get("S", ""),
                "user_id": item.get("user_id", {}).get("S", ""),
                "task_arn": item.get("task_arn", {}).get("S", ""),
                "status": item.get("status", {}).get("S", ""),
                "pk": item.get("pk", {}).get("S", ""),
                "sk": item.get("sk", {}).get("S", ""),
                "created_at": item.get("created_at", {}).get("S", ""),
            })

        if "LastEvaluatedKey" not in response:
            break
        scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

    return containers


def stop_ecs_task_if_exists(ecs_client, cluster_name: str, task_arn: str):
    """Stop an ECS task if it exists."""
    if not task_arn:
        return False

    try:
        ecs_client.stop_task(
            cluster=cluster_name,
            task=task_arn,
            reason="Cleanup: removing pending/failed tasks",
        )
        print(f"  ✓ Stopped ECS task: {task_arn}")
        return True
    except ecs_client.exceptions.InvalidParameterException:
        # Task doesn't exist or already stopped
        print(f"  ⓘ ECS task not found or already stopped: {task_arn}")
        return False
    except Exception as e:
        print(f"  ✗ Error stopping ECS task {task_arn}: {e}")
        return False


def delete_container(dynamodb_client, table_name: str, pk: str, sk: str):
    """Delete a container record from DynamoDB."""
    try:
        dynamodb_client.delete_item(
            TableName=table_name,
            Key={"pk": {"S": pk}, "sk": {"S": sk}},
        )
        print(f"  ✓ Deleted from DynamoDB")
        return True
    except Exception as e:
        print(f"  ✗ Error deleting from DynamoDB: {e}")
        return False


def cleanup_containers(
    env: str = "dev",
    dry_run: bool = False,
    profile: str = "personal",
    region: str = "ap-southeast-2",
    cluster_name: str = "clawtalk-dev",
):
    """Clean up pending and failed containers."""
    table_name = f"openclaw-containers-{env}"

    session = boto3.Session(profile_name=profile, region_name=region)
    dynamodb_client = session.client("dynamodb")
    ecs_client = session.client("ecs")

    print(f"==> Cleaning up PENDING and FAILED containers from table: {table_name}")
    print(f"==> ECS cluster: {cluster_name}")
    print()

    print("Scanning for PENDING containers...")
    pending_containers = get_containers_by_status(dynamodb_client, table_name, "PENDING")
    print(f"Found {len(pending_containers)} PENDING containers")

    print("\nScanning for FAILED containers...")
    failed_containers = get_containers_by_status(dynamodb_client, table_name, "FAILED")
    print(f"Found {len(failed_containers)} FAILED containers")

    all_containers = pending_containers + failed_containers

    if not all_containers:
        print("\nNo pending or failed containers found.")
        return

    print(f"\n{'='*60}")
    print(f"Total containers to clean up: {len(all_containers)}")
    print(f"{'='*60}\n")

    if dry_run:
        print("⚠️  DRY RUN MODE - No changes will be made\n")

    for container in all_containers:
        print(f"Container: {container['container_id']}")
        print(f"  User: {container['user_id']}")
        print(f"  Status: {container['status']}")
        print(f"  Created: {container['created_at']}")

        if dry_run:
            if container['task_arn']:
                print(f"  [DRY RUN] Would stop ECS task: {container['task_arn']}")
            print(f"  [DRY RUN] Would delete from DynamoDB (pk={container['pk']}, sk={container['sk']})")
        else:
            # Stop ECS task if it exists
            if container['task_arn']:
                stop_ecs_task_if_exists(ecs_client, cluster_name, container['task_arn'])

            # Delete from DynamoDB
            delete_container(
                dynamodb_client,
                table_name,
                container['pk'],
                container['sk'],
            )

        print()

    print(f"{'='*60}")
    if dry_run:
        print(f"✓ DRY RUN COMPLETE - Would have cleaned up {len(all_containers)} containers")
    else:
        print(f"✓ CLEANUP COMPLETE - Removed {len(all_containers)} containers")
    print(f"{'='*60}")


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Clean up pending and failed ECS tasks and DynamoDB records"
    )
    parser.add_argument(
        "--env",
        default="dev",
        help="Environment (dev/prod)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting",
    )
    parser.add_argument(
        "--profile",
        default="personal",
        help="AWS profile name",
    )
    parser.add_argument(
        "--region",
        default="ap-southeast-2",
        help="AWS region",
    )
    parser.add_argument(
        "--cluster",
        default="clawtalk-dev",
        help="ECS cluster name",
    )

    args = parser.parse_args()

    try:
        cleanup_containers(
            env=args.env,
            dry_run=args.dry_run,
            profile=args.profile,
            region=args.region,
            cluster_name=args.cluster,
        )
    except Exception as e:
        print(f"ERROR: {e}")
        import sys
        sys.exit(1)


if __name__ == "__main__":
    main()
