import os
import sys

from mangum import Mangum

from app.main import app
from app.services.ecs import handle_task_event
from app.services.kubernetes import (
    PROVISION_EVENT_SOURCE,
    PROVISION_EVENT_TYPE,
    poll_k8s_container_statuses,
    provision_pod,
)

# Create Mangum handler for API Gateway events
mangum_handler = Mangum(app, lifespan="auto")


def handler(event, context):
    """
    Lambda handler supporting multiple event sources.

    Routes EventBridge ECS task state changes to handle_task_event,
    routes async k8s pod-provision requests to provision_pod,
    and forwards API Gateway HTTP requests to the FastAPI app via Mangum.
    """
    # EventBridge: scheduled k8s status poll (cron rule fires every 60 s)
    if event.get("source") == "aws.events" and event.get("detail-type") == "Scheduled Event":
        result = poll_k8s_container_statuses()
        return {"statusCode": 200, "body": f"k8s poll complete: {result}"}

    # EventBridge: ECS task state changes
    if event.get("source") == "aws.ecs":
        handle_task_event(event)
        return {"statusCode": 200, "body": "Event processed"}

    # Async self-invocation: k8s pod provisioning (fired by _dispatch_provision)
    if (
        event.get("source") == PROVISION_EVENT_SOURCE
        and event.get("detail-type") == PROVISION_EVENT_TYPE
    ):
        provision_pod(event["detail"])
        return {"statusCode": 200, "body": "Pod provisioned"}

    # Default: API Gateway / HTTP request
    return mangum_handler(event, context)
