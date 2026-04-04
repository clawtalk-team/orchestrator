from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class HealthData(BaseModel):
    agents_running: int = 0
    uptime_seconds: int = 0
    memory_mb: int = 0
    cpu_percent: float = 0.0
    version: str = "0.1.0"
    agents: List[Dict[str, Any]] = Field(default_factory=list)


class Container(BaseModel):
    container_id: str
    user_id: str
    task_arn: str
    status: str = "PENDING"  # PENDING, RUNNING, STOPPED, FAILED
    ip_address: Optional[str] = None
    port: int = 8080
    health_endpoint: Optional[str] = None
    api_endpoint: Optional[str] = None
    health_status: str = "UNKNOWN"  # HEALTHY, UNHEALTHY, UNREACHABLE, STARTING, UNKNOWN
    last_health_check: Optional[datetime] = None
    health_data: Optional[HealthData] = None
    created_at: datetime
    updated_at: datetime


class ContainerRequest(BaseModel):
    name: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class ContainerResponse(BaseModel):
    container_id: str
    status: str
    ip_address: Optional[str] = None
    health_status: str
    created_at: datetime
    updated_at: datetime


class ContainerHealthResponse(BaseModel):
    container_id: str
    health_status: str
    last_health_check: Optional[datetime] = None
    health_data: Optional[HealthData] = None
