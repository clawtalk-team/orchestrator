"""
Pydantic models for configuration API.

Supports flexible JSON schemas for user and system configurations.
"""

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class ConfigBase(BaseModel):
    """Base configuration model with common fields."""

    model_config = ConfigDict(extra="allow")  # Allow arbitrary fields


class UserConfigCreate(ConfigBase):
    """Request model for creating a user configuration."""

    config_name: str = Field(
        ...,
        description="Name of the configuration (e.g., 'default', 'production', 'development')",
        min_length=1,
        max_length=100
    )

    # Optional standard fields
    llm_provider: Optional[str] = Field(
        None,
        description="LLM provider (anthropic, openai, openrouter)"
    )
    openclaw_model: Optional[str] = Field(
        None,
        description="Model name for OpenClaw"
    )
    anthropic_api_key: Optional[str] = Field(
        None,
        description="Anthropic API key"
    )
    openai_api_key: Optional[str] = Field(
        None,
        description="OpenAI API key"
    )
    openrouter_api_key: Optional[str] = Field(
        None,
        description="OpenRouter API key"
    )
    auth_gateway_api_key: Optional[str] = Field(
        None,
        description="Auth Gateway API key"
    )
    openclaw_token: Optional[str] = Field(
        None,
        description="OpenClaw authentication token"
    )
    max_containers: Optional[int] = Field(
        None,
        description="Maximum number of containers allowed",
        ge=0
    )

    model_config = ConfigDict(
        extra="allow",  # Allow arbitrary additional fields
        json_schema_extra={
            "example": {
                "config_name": "production",
                "llm_provider": "anthropic",
                "openclaw_model": "claude-3-haiku-20240307",
                "anthropic_api_key": "sk-ant-api03-...",
                "max_containers": 10,
                "custom_field": "custom_value"
            }
        }
    )


class UserConfigUpdate(ConfigBase):
    """Request model for updating a user configuration."""

    # All fields optional for updates (partial updates supported)
    llm_provider: Optional[str] = None
    openclaw_model: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    auth_gateway_api_key: Optional[str] = None
    openclaw_token: Optional[str] = None
    max_containers: Optional[int] = Field(None, ge=0)

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "anthropic_api_key": "sk-ant-new-key",
                "max_containers": 15
            }
        }
    )


class UserConfigResponse(ConfigBase):
    """Response model for user configuration."""

    config_name: str = Field(..., description="Name of the configuration")
    user_id: str = Field(..., description="User ID who owns this config")
    created_at: str = Field(..., description="ISO 8601 timestamp when created")
    updated_at: str = Field(..., description="ISO 8601 timestamp when last updated")

    # Optional user config fields
    llm_provider: Optional[str] = None
    openclaw_model: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    auth_gateway_api_key: Optional[str] = None
    openclaw_token: Optional[str] = None
    max_containers: Optional[int] = None

    # System config fields (included when merged=true)
    auth_gateway_url: Optional[str] = Field(
        None, description="Auth gateway URL (from system config)"
    )
    openclaw_url: Optional[str] = Field(
        None, description="OpenClaw gateway URL (from system config)"
    )
    voice_gateway_url: Optional[str] = Field(
        None, description="Voice gateway URL (from system config)"
    )

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "config_name": "production",
                "user_id": "user-123",
                "llm_provider": "anthropic",
                "openclaw_model": "claude-3-haiku-20240307",
                "anthropic_api_key": "sk-ant-api03-...",
                "max_containers": 10,
                "created_at": "2026-04-08T10:00:00Z",
                "updated_at": "2026-04-08T10:00:00Z"
            }
        }
    )


class SystemConfigUpdate(BaseModel):
    """Request model for updating system configuration."""

    auth_gateway_url: Optional[str] = Field(
        None,
        description="Auth Gateway URL"
    )
    openclaw_url: Optional[str] = Field(
        None,
        description="OpenClaw Gateway URL"
    )
    openclaw_token: Optional[str] = Field(
        None,
        description="OpenClaw authentication token"
    )
    voice_gateway_url: Optional[str] = Field(
        None,
        description="Voice Gateway URL"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "auth_gateway_url": "http://auth-gateway:8001",
                "openclaw_url": "http://openclaw:18789",
                "voice_gateway_url": "ws://voice-gateway:9090"
            }
        }
    )


class SystemConfigResponse(BaseModel):
    """Response model for system configuration."""

    auth_gateway_url: Optional[str] = Field(None, description="Auth Gateway URL")
    openclaw_url: Optional[str] = Field(None, description="OpenClaw Gateway URL")
    openclaw_token: Optional[str] = Field(None, description="OpenClaw authentication token")
    voice_gateway_url: Optional[str] = Field(None, description="Voice Gateway URL")
    updated_at: Optional[str] = Field(None, description="ISO 8601 timestamp when last updated")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "auth_gateway_url": "http://localhost:8001",
                "openclaw_url": "http://localhost:18789",
                "voice_gateway_url": "ws://localhost:9090",
                "updated_at": "2026-04-08T10:00:00Z"
            }
        }
    )
