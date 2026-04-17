from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class HealthData(BaseModel):
    """Health metrics from a running container."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "agents_running": 2,
                "uptime_seconds": 3600,
                "memory_mb": 512,
                "cpu_percent": 25.5,
                "version": "0.1.0",
                "agents": [
                    {"id": "agent-1", "status": "running", "type": "claw"},
                    {"id": "agent-2", "status": "running", "type": "claw"},
                ],
            }
        }
    )

    agents_running: int = Field(
        default=0, description="Number of active agents running in the container"
    )
    uptime_seconds: int = Field(default=0, description="Container uptime in seconds")
    memory_mb: int = Field(default=0, description="Memory usage in megabytes")
    cpu_percent: float = Field(default=0.0, description="CPU usage percentage")
    version: str = Field(default="0.1.0", description="Container image version")
    agents: List[Dict[str, Any]] = Field(
        default_factory=list, description="List of running agents with their details"
    )


class Container(BaseModel):
    """Internal container model with full details."""

    container_id: str = Field(description="Unique identifier for the container")
    user_id: str = Field(description="User ID that owns this container")
    task_arn: str = Field(description="AWS ECS task ARN")
    status: str = Field(
        default="PENDING",
        description="Container lifecycle status: PENDING, RUNNING, STOPPED, FAILED",
    )
    ip_address: Optional[str] = Field(
        default=None, description="Container IP address once running"
    )
    port: int = Field(default=8080, description="Container port number")
    health_endpoint: Optional[str] = Field(
        default=None, description="Full URL to health check endpoint"
    )
    api_endpoint: Optional[str] = Field(
        default=None, description="Full URL to container API endpoint"
    )
    health_status: str = Field(
        default="UNKNOWN",
        description="Health check status: HEALTHY, UNHEALTHY, UNREACHABLE, STARTING, UNKNOWN",
    )
    last_health_check: Optional[datetime] = Field(
        default=None, description="Timestamp of last successful health check"
    )
    health_data: Optional[HealthData] = Field(
        default=None, description="Detailed health metrics from the container"
    )
    created_at: datetime = Field(description="Timestamp when container was created")
    updated_at: datetime = Field(
        description="Timestamp when container was last updated"
    )

    def to_response(self) -> "ContainerResponse":
        """Convert Container model to ContainerResponse for API responses."""
        return ContainerResponse(
            container_id=self.container_id,
            task_arn=self.task_arn or None,
            status=self.status,
            ip_address=self.ip_address,
            health_status=self.health_status,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class ContainerRequest(BaseModel):
    """Request to create a new container."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "my-agent-container",
                "config_name": "default",
                "env_vars": {"DEBUG": "true"},
            }
        }
    )

    name: Optional[str] = Field(
        default=None, description="Optional container name for identification"
    )
    config_name: Optional[str] = Field(
        default="default", description="Named configuration to use (default: 'default')"
    )
    env_vars: Optional[Dict[str, str]] = Field(
        default=None,
        description="Additional environment variables to pass to the container (e.g. {'DEBUG': 'true'})",
    )


class ContainerResponse(BaseModel):
    """Container details returned to the client."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "container_id": "cnt-abc123def456",
                "task_arn": "arn:aws:ecs:ap-southeast-2:826182175287:task/clawtalk-dev/abc123",
                "status": "RUNNING",
                "ip_address": "10.0.1.42",
                "health_status": "HEALTHY",
                "created_at": "2026-04-07T10:00:00Z",
                "updated_at": "2026-04-07T10:05:00Z",
            }
        }
    )

    container_id: str = Field(description="Unique identifier for the container")
    task_arn: Optional[str] = Field(
        default=None, description="AWS ECS task ARN (available after task creation)"
    )
    status: str = Field(
        description="Current container status: PENDING, RUNNING, STOPPED, FAILED"
    )
    ip_address: Optional[str] = Field(
        default=None, description="Container IP address (available when running)"
    )
    health_status: str = Field(
        description="Health check status: HEALTHY, UNHEALTHY, UNREACHABLE, STARTING, UNKNOWN"
    )
    created_at: datetime = Field(description="Timestamp when container was created")
    updated_at: datetime = Field(
        description="Timestamp when container was last updated"
    )


class ContainerHealthResponse(BaseModel):
    """Detailed health information for a container."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "container_id": "cnt-abc123def456",
                "health_status": "HEALTHY",
                "last_health_check": "2026-04-07T10:05:00Z",
                "health_data": {
                    "agents_running": 2,
                    "uptime_seconds": 3600,
                    "memory_mb": 512,
                    "cpu_percent": 25.5,
                    "version": "0.1.0",
                    "agents": [],
                },
            }
        }
    )

    container_id: str = Field(description="Unique identifier for the container")
    health_status: str = Field(
        description="Current health status: HEALTHY, UNHEALTHY, UNREACHABLE, STARTING, UNKNOWN"
    )
    last_health_check: Optional[datetime] = Field(
        default=None, description="Timestamp of last successful health check"
    )
    health_data: Optional[HealthData] = Field(
        default=None, description="Detailed health metrics from the container"
    )
