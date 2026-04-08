from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request

from app.models.container import (ContainerHealthResponse, ContainerRequest,
                                  ContainerResponse)
from app.services import dynamodb, ecs

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
    """
    user_id = request.state.user_id
    api_key = request.state.api_key

    # Create container (will auto-create config if not exists)
    container = ecs.create_container(
        user_id=user_id,
        api_key=api_key,
        config_name=req.config_name or "default",
    )
    return ContainerResponse(
        container_id=container.container_id,
        task_arn=container.task_arn if container.task_arn else None,
        status=container.status,
        ip_address=container.ip_address,
        health_status=container.health_status,
        created_at=container.created_at,
        updated_at=container.updated_at,
    )


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
    return [
        ContainerResponse(
            container_id=c.container_id,
            task_arn=c.task_arn if c.task_arn else None,
            status=c.status,
            ip_address=c.ip_address,
            health_status=c.health_status,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in containers
    ]


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
        raise HTTPException(status_code=404, detail="Container not found")

    return ContainerResponse(
        container_id=container.container_id,
        task_arn=container.task_arn if container.task_arn else None,
        status=container.status,
        ip_address=container.ip_address,
        health_status=container.health_status,
        created_at=container.created_at,
        updated_at=container.updated_at,
    )


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
        raise HTTPException(status_code=404, detail="Container not found")

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
