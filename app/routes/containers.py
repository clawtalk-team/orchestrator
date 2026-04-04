from fastapi import APIRouter, Request, HTTPException
from typing import List, Optional

from app.models.container import ContainerRequest, ContainerResponse, ContainerHealthResponse
from app.services import ecs, dynamodb

router = APIRouter(prefix="/containers", tags=["containers"])


@router.post("", response_model=ContainerResponse)
async def create_container(request: Request, req: ContainerRequest):
    """Create a new container for the authenticated user."""
    user_id = request.state.user_id

    try:
        container = ecs.create_container(
            user_id=user_id,
            config=req.config,
        )
        return ContainerResponse(
            container_id=container.container_id,
            status=container.status,
            ip_address=container.ip_address,
            health_status=container.health_status,
            created_at=container.created_at,
            updated_at=container.updated_at,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create container: {str(e)}")


@router.get("", response_model=List[ContainerResponse])
async def list_containers(request: Request, status: Optional[str] = None):
    """List all containers for the authenticated user."""
    user_id = request.state.user_id

    containers = dynamodb.get_user_containers(user_id=user_id, status=status)
    return [
        ContainerResponse(
            container_id=c.container_id,
            status=c.status,
            ip_address=c.ip_address,
            health_status=c.health_status,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in containers
    ]


@router.get("/{container_id}", response_model=ContainerResponse)
async def get_container(request: Request, container_id: str):
    """Get details of a specific container."""
    user_id = request.state.user_id

    container = dynamodb.get_container(user_id=user_id, container_id=container_id)
    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    return ContainerResponse(
        container_id=container.container_id,
        status=container.status,
        ip_address=container.ip_address,
        health_status=container.health_status,
        created_at=container.created_at,
        updated_at=container.updated_at,
    )


@router.delete("/{container_id}", status_code=204)
async def delete_container(request: Request, container_id: str):
    """Delete/stop a container."""
    user_id = request.state.user_id

    container = dynamodb.get_container(user_id=user_id, container_id=container_id)
    if not container:
        raise HTTPException(status_code=404, detail="Container not found")

    try:
        ecs.stop_container(user_id=user_id, container_id=container_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop container: {str(e)}")


@router.get("/{container_id}/health", response_model=ContainerHealthResponse)
async def get_container_health(request: Request, container_id: str):
    """Get health status of a specific container."""
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
