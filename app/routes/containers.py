import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request

from app.models.container import (ContainerHealthResponse, ContainerRequest,
                                  ContainerResponse)
from app.services import dynamodb, ecs

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/containers", tags=["containers"])


@router.post(
    "",
    response_model=ContainerResponse,
    summary="Create a new container",
    response_description="Container created successfully",
)
async def create_container(request: Request, req: ContainerRequest):
    """
    Create a new container for the authenticated user.

    The container will be deployed as an ECS task and will start in PENDING status.
    Once the task is running and health checks pass, the status will change to RUNNING
    and an IP address will be assigned.

    The API key from the Authorization header will be stored in DynamoDB for the container
    to use for authentication with other services. If a named config does not exist, it will
    be created with default values.

    Optional environment variables can be passed in the request body to customize container
    behavior (e.g. DEBUG=true for verbose logging).
    """
    user_id = request.state.user_id
    api_key = request.state.api_key
    config_name = req.config_name or "default"

    logger.info("create_container: user=%s config=%s", user_id, config_name)
    container = ecs.create_container(
        user_id=user_id,
        api_key=api_key,
        config_name=config_name,
        env_vars=req.env_vars,
    )
    logger.info(
        "create_container done: user=%s container=%s status=%s",
        user_id,
        container.container_id,
        container.status,
    )
    return container.to_response()


@router.get(
    "",
    response_model=List[ContainerResponse],
    summary="List all containers",
    response_description="List of containers for the authenticated user",
)
async def list_containers(
    request: Request,
    status: Optional[str] = None,
):
    """
    List all containers for the authenticated user.

    Optionally filter by status:
    - **PENDING**: Container is being created
    - **RUNNING**: Container is active
    - **STOPPED**: Container has been stopped
    - **FAILED**: Container failed to start or crashed
    """
    user_id = request.state.user_id

    containers = dynamodb.get_user_containers(user_id=user_id, status=status)
    return [c.to_response() for c in containers]


@router.get(
    "/{container_id}",
    response_model=ContainerResponse,
    summary="Get container details",
    response_description="Container details",
    responses={
        404: {"description": "Container not found"},
    },
)
async def get_container(request: Request, container_id: str):
    """
    Get details of a specific container.

    Returns the current status, IP address, health status, and timestamps
    for the specified container.
    """
    user_id = request.state.user_id

    container = dynamodb.get_container(user_id=user_id, container_id=container_id)
    if not container:
        logger.warning("get_container: not found user=%s container=%s", user_id, container_id)
        raise HTTPException(status_code=404, detail="Container not found")

    return container.to_response()


@router.delete(
    "/{container_id}",
    status_code=204,
    summary="Delete a container",
    response_description="Container deleted successfully",
    responses={
        404: {"description": "Container not found"},
    },
)
async def delete_container(request: Request, container_id: str):
    """
    Delete and stop a container.

    This will stop the ECS task and mark the container as STOPPED.
    The container record will remain in the database for audit purposes.
    """
    user_id = request.state.user_id

    container = dynamodb.get_container(user_id=user_id, container_id=container_id)
    if not container:
        logger.warning("delete_container: not found user=%s container=%s", user_id, container_id)
        raise HTTPException(status_code=404, detail="Container not found")

    logger.info("delete_container: user=%s container=%s", user_id, container_id)
    ecs.stop_container(user_id=user_id, container_id=container_id)


@router.get(
    "/{container_id}/health",
    response_model=ContainerHealthResponse,
    summary="Get container health",
    response_description="Container health status and metrics",
    responses={
        404: {"description": "Container not found"},
    },
)
async def get_container_health(request: Request, container_id: str):
    """
    Get detailed health status of a specific container.

    Returns health check status along with detailed metrics including:
    - Number of running agents
    - Container uptime
    - Memory and CPU usage
    - Agent details
    """
    user_id = request.state.user_id

    container = dynamodb.get_container(user_id=user_id, container_id=container_id)
    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    return ContainerHealthResponse(
        container_id=container.container_id,
        health_status=container.health_status,
        last_health_check=container.last_health_check,
        health_data=container.health_data,
    )
