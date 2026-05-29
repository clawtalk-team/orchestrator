from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ClusterResponse(BaseModel):
    """A registered compute cluster."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "k3s-prod",
                "backend": "k8s",
                "namespace": "openclaw",
                "registered_at": "2026-05-13T09:21:40Z",
                "last_seen_at": "2026-05-29T03:17:09Z",
            }
        }
    )

    name: str = Field(description="Cluster identifier (K8S_CLUSTER_NAME or ECS cluster name)")
    backend: str = Field(description="Compute backend: 'ecs' or 'k8s'")
    namespace: str = Field(default="", description="Kubernetes namespace (empty for ECS)")
    registered_at: datetime = Field(description="When this cluster was first used")
    last_seen_at: datetime = Field(description="When this cluster last had a container dispatched to it")
