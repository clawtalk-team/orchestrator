import os
import sys

from mangum import Mangum

from app.main import app
from app.services.ecs import handle_task_event

# Create Mangum handler for API Gateway events
mangum_handler = Mangum(app, lifespan="auto")


def handler(event, context):
    """
    Lambda handler supporting multiple event sources.

    Routes EventBridge ECS task state changes to handle_task_event,
    and API Gateway HTTP requests to the FastAPI app via Mangum.
    """
    # Check if this is an EventBridge event
    if event.get("source") == "aws.ecs":
        # Handle ECS task state change events
        handle_task_event(event)
        return {"statusCode": 200, "body": "Event processed"}

    # Default to API Gateway/HTTP request handling
    return mangum_handler(event, context)
