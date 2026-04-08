from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.utils import get_git_sha


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(description="Service health status")
    service: str = Field(description="Service name")
    git_sha: Optional[str] = Field(
        default=None, description="Git commit SHA (short format)"
    )


router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health check",
    response_description="Service is healthy",
)
def health():
    """
    Health check endpoint for the orchestrator service.

    This endpoint does not require authentication and can be used
    for load balancer health checks or monitoring systems.

    Returns the service status, service name, and git commit SHA.
    """
    return {"status": "ok", "service": "orchestrator", "git_sha": get_git_sha()}
