#!/usr/bin/env python3
"""
Delete one or more openclaw-agent containers.
Stops the ECS task and removes the DynamoDB record.

Usage:
  # Delete single container
  python scripts/delete_containers.py CONTAINER_ID --user-id USER_ID [--env ENV]

  # Delete multiple containers
  python scripts/delete_containers.py CONTAINER_ID1 CONTAINER_ID2 ... --user-id USER_ID [--env ENV]

  # Delete all containers for a user
  python scripts/delete_containers.py --user-id USER_ID --all [--env ENV]

  # Delete by status (e.g., all STOPPED containers)
  python scripts/delete_containers.py --user-id USER_ID --status STOPPED [--env ENV]
"""

import argparse
import boto3
import sys
from typing import List, Optional


def get_containers(
    user_id: str,
    env: str,
    profile: str,
    region: str,
    status: Optional[str] = None
) -> List[dict]:
    """Get containers for a user, optionally filtered by status."""
    table_name = f"openclaw-containers-{env}"

    session = boto3.Session(profile_name=profile, region_name=region)
    dynamodb = session.client("dynamodb")

    print(f"==> Fetching containers for user {user_id}...")

    # Build query with optional status filter
    query_kwargs = {
        "TableName": table_name,
        "KeyConditionExpression": "pk = :pk",
        "ExpressionAttributeValues": {":pk": {"S": f"USER#{user_id}"}}
    }
    if status:
        query_kwargs["FilterExpression"] = "#s = :status"
        query_kwargs["ExpressionAttributeNames"] = {"#s": "status"}
        query_kwargs["ExpressionAttributeValues"][":status"] = {"S": status}

    # Query with pagination
    containers = []
    while True:
        response = dynamodb.query(**query_kwargs)

        # Parse items
        for item in response.get("Items", []):
            container = {
                "container_id": item.get("sk", {}).get("S", "").replace("CONTAINER#", ""),
                "user_id": item.get("user_id", {}).get("S", ""),
                "status": item.get("status", {}).get("S", ""),
                "task_arn": item.get("task_arn", {}).get("S", ""),
                "pk": item.get("pk", {}).get("S", ""),
                "sk": item.get("sk", {}).get("S", "")
            }
            containers.append(container)

        # Handle pagination
        if "LastEvaluatedKey" not in response:
            break
        query_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

    return containers


def delete_container(
    container: dict,
    env: str,
    profile: str,
    region: str,
    cluster: str,
    dry_run: bool = False
):
    """Delete a single container."""
    container_id = container["container_id"]
    task_arn = container["task_arn"]
    table_name = f"openclaw-containers-{env}"

    session = boto3.Session(profile_name=profile, region_name=region)
    ecs = session.client("ecs")
    dynamodb = session.client("dynamodb")

    print(f"\n==> Deleting container: {container_id}")
    print(f"    Status: {container['status']}")
    print(f"    Task ARN: {task_arn}")

    if dry_run:
        print("    [DRY RUN - no changes made]")
        return

    # Stop ECS task if it exists and is running
    if task_arn and task_arn != "None":
        try:
            print(f"    Stopping ECS task...")
            ecs.stop_task(
                cluster=cluster,
                task=task_arn,
                reason=f"Container {container_id} deleted via script"
            )
            print(f"    ✓ ECS task stopped")
        except ecs.exceptions.ClientException as e:
            if "not found" in str(e).lower():
                print(f"    ⚠ Task not found in ECS (may already be stopped)")
            else:
                print(f"    ✗ Error stopping task: {e}")
        except Exception as e:
            print(f"    ✗ Error stopping task: {e}")

    # Delete DynamoDB record
    try:
        print(f"    Deleting DynamoDB record...")
        dynamodb.delete_item(
            TableName=table_name,
            Key={
                "pk": {"S": container["pk"]},
                "sk": {"S": container["sk"]}
            }
        )
        print(f"    ✓ DynamoDB record deleted")
    except Exception as e:
        print(f"    ✗ Error deleting from DynamoDB: {e}")


def main():
    parser = argparse.ArgumentParser(description="Delete openclaw-agent containers")
    parser.add_argument("container_ids", nargs="*", help="Container IDs to delete")
    parser.add_argument("--user-id", required=True, help="User ID who owns the containers")
    parser.add_argument("--all", action="store_true", help="Delete all containers for the user")
    parser.add_argument("--status", help="Delete containers with specific status (e.g., STOPPED)")
    parser.add_argument("--env", default="dev", help="Environment (dev/prod)")
    parser.add_argument("--profile", default="personal", help="AWS profile name")
    parser.add_argument("--region", default="ap-southeast-2", help="AWS region")
    parser.add_argument("--cluster", default="clawtalk-dev", help="ECS cluster name")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without deleting")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")

    args = parser.parse_args()

    # Determine which containers to delete
    containers_to_delete = []

    if args.all or args.status:
        # Fetch containers based on criteria
        containers_to_delete = get_containers(
            args.user_id,
            args.env,
            args.profile,
            args.region,
            status=args.status
        )

        if not containers_to_delete:
            print("No containers found matching criteria.")
            sys.exit(0)

    elif args.container_ids:
        # Delete specific containers
        session = boto3.Session(profile_name=args.profile, region_name=args.region)
        dynamodb = session.client("dynamodb")
        table_name = f"openclaw-containers-{args.env}"

        for container_id in args.container_ids:
            response = dynamodb.get_item(
                TableName=table_name,
                Key={
                    "pk": {"S": f"USER#{args.user_id}"},
                    "sk": {"S": f"CONTAINER#{container_id}"}
                }
            )

            item = response.get("Item")
            if not item:
                print(f"Warning: Container {container_id} not found")
                continue

            container = {
                "container_id": item.get("sk", {}).get("S", "").replace("CONTAINER#", ""),
                "user_id": item.get("user_id", {}).get("S", ""),
                "status": item.get("status", {}).get("S", ""),
                "task_arn": item.get("task_arn", {}).get("S", ""),
                "pk": item.get("pk", {}).get("S", ""),
                "sk": item.get("sk", {}).get("S", "")
            }
            containers_to_delete.append(container)
    else:
        parser.error("Provide container IDs, --all, or --status")

    # Show summary
    print(f"\n{'=' * 60}")
    print(f"Containers to delete ({len(containers_to_delete)}):")
    print(f"{'=' * 60}")
    for container in containers_to_delete:
        print(f"  - {container['container_id']} (Status: {container['status']})")

    if args.dry_run:
        print("\n[DRY RUN MODE - no changes will be made]")
    else:
        # Confirm deletion
        if not args.yes:
            response = input(f"\nDelete {len(containers_to_delete)} container(s)? [y/N]: ")
            if response.lower() not in ["y", "yes"]:
                print("Aborted.")
                sys.exit(0)

    # Delete containers
    for container in containers_to_delete:
        delete_container(
            container,
            args.env,
            args.profile,
            args.region,
            args.cluster,
            dry_run=args.dry_run
        )

    print(f"\n{'=' * 60}")
    if args.dry_run:
        print(f"DRY RUN: Would have deleted {len(containers_to_delete)} container(s)")
    else:
        print(f"✓ Deleted {len(containers_to_delete)} container(s)")


if __name__ == "__main__":
    main()
