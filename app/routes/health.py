from fastapi import APIRouter
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(description="Service health status")
    service: str = Field(description="Service name")


router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health check",
    response_description="Service is healthy",
)
async def health():
    """
    Health check endpoint for the orchestrator service.

    This endpoint does not require authentication and can be used
    for load balancer health checks or monitoring systems.
    """
    return {"status": "ok", "service": "orchestrator"}
