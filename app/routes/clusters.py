import hmac
from typing import List

from fastapi import APIRouter, HTTPException, Request, status

from app.config import get_settings
from app.models.cluster import ClusterResponse
from app.services import dynamodb

router = APIRouter(prefix="/clusters", tags=["clusters"])


def _require_admin(request: Request) -> None:
    settings = get_settings()
    api_key = getattr(request.state, "api_key", None)
    if not settings.master_api_key or not api_key or not hmac.compare_digest(api_key, settings.master_api_key):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")


@router.get(
    "",
    response_model=List[ClusterResponse],
    summary="List registered clusters",
    response_description="All clusters the orchestrator has dispatched to",
    responses={403: {"description": "Admin access required"}},
)
async def list_clusters(request: Request) -> List[ClusterResponse]:
    """
    List all clusters registered in the cluster registry.

    A cluster is registered automatically the first time a container is dispatched
    to it. Records include when the cluster was first seen and last used.

    Requires admin access (master API key).
    """
    _require_admin(request)
    return [ClusterResponse(**c) for c in dynamodb.get_clusters()]


@router.get(
    "/{name}",
    response_model=ClusterResponse,
    summary="Get a registered cluster",
    response_description="Cluster details",
    responses={
        403: {"description": "Admin access required"},
        404: {"description": "Cluster not found"},
    },
)
async def get_cluster(request: Request, name: str) -> ClusterResponse:
    """
    Get details of a specific registered cluster by name.

    Requires admin access (master API key).
    """
    _require_admin(request)
    cluster = dynamodb.get_cluster(name)
    if not cluster:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Cluster '{name}' not found")
    return ClusterResponse(**cluster)


@router.delete(
    "/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deregister a cluster",
    responses={
        403: {"description": "Admin access required"},
        404: {"description": "Cluster not found"},
    },
)
async def delete_cluster(request: Request, name: str) -> None:
    """
    Remove a cluster from the registry.

    This only removes the registry entry — it does not affect any running containers
    or pods on the cluster. The cluster will be re-registered automatically if a new
    container is dispatched to it.

    Requires admin access (master API key).
    """
    _require_admin(request)
    if not dynamodb.delete_cluster(name):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Cluster '{name}' not found")
