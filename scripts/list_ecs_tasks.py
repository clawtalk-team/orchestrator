#!/usr/bin/env python3
"""
List all actual ECS tasks for openclaw-agent.
Shows tasks running in the ECS cluster.

Usage: python scripts/list_ecs_tasks.py [--env ENV]
"""

import argparse

import boto3
from tabulate import tabulate


def list_ecs_tasks(
    env: str = "dev",
    profile: str = "personal",
    region: str = "ap-southeast-2",
    cluster: str = "clawtalk-dev",
):
    """List all ECS tasks in the cluster."""
    session = boto3.Session(profile_name=profile, region_name=region)
    ecs = session.client("ecs")

    print(f"==> Listing ECS tasks in cluster: {cluster}\n")

    # List all tasks with pagination
    task_arns = []
    list_kwargs = {"cluster": cluster}
    while True:
        response = ecs.list_tasks(**list_kwargs)
        task_arns.extend(response.get("taskArns", []))
        if "nextToken" not in response:
            break
        list_kwargs["nextToken"] = response["nextToken"]

    if not task_arns:
        print("No tasks found in cluster.")
        return

    # Describe tasks in batches (max 100 per call)
    tasks = []
    for i in range(0, len(task_arns), 100):
        chunk = task_arns[i : i + 100]
        tasks_response = ecs.describe_tasks(
            cluster=cluster, tasks=chunk, include=["TAGS"]
        )
        tasks.extend(tasks_response.get("tasks", []))

    # Parse tasks into table format
    table_data = []
    for task in tasks:
        task_id = task["taskArn"].split("/")[-1]
        status = task.get("lastStatus", "")
        desired_status = task.get("desiredStatus", "")
        started_at = task.get("startedAt", "")

        # Extract tags
        tags = {tag["key"]: tag["value"] for tag in task.get("tags", [])}
        container_id = tags.get("container_id", "")
        user_id = tags.get("user_id", "")

        # Get IP address from network interfaces
        ip_address = ""
        for attachment in task.get("attachments", []):
            if attachment.get("type") == "ElasticNetworkInterface":
                for detail in attachment.get("details", []):
                    if detail["name"] == "privateIPv4Address":
                        ip_address = detail["value"]
                        break

        table_data.append(
            [
                task_id,
                status,
                desired_status,
                container_id,
                user_id,
                ip_address,
                started_at,
            ]
        )

    headers = [
        "Task ID",
        "Status",
        "Desired",
        "Container ID",
        "User ID",
        "IP Address",
        "Started At",
    ]
    print(tabulate(table_data, headers=headers, tablefmt="grid"))

    # Count by status
    print("\n==> Task count by status:")
    running = ecs.list_tasks(cluster=cluster, desiredStatus="RUNNING")
    stopped = ecs.list_tasks(cluster=cluster, desiredStatus="STOPPED")
    print(f"  RUNNING: {len(running.get('taskArns', []))}")
    print(f"  STOPPED: {len(stopped.get('taskArns', []))}")


def main():
    parser = argparse.ArgumentParser(description="List ECS tasks for openclaw-agent")
    parser.add_argument("--env", default="dev", help="Environment (dev/prod)")
    parser.add_argument("--profile", default="personal", help="AWS profile name")
    parser.add_argument("--region", default="ap-southeast-2", help="AWS region")
    parser.add_argument("--cluster", default="clawtalk-dev", help="ECS cluster name")

    args = parser.parse_args()

    list_ecs_tasks(
        env=args.env, profile=args.profile, region=args.region, cluster=args.cluster
    )


if __name__ == "__main__":
    main()
