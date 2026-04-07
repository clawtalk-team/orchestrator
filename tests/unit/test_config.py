"""Unit tests for configuration."""
import os

import pytest

from app.config import Settings, get_settings


def test_get_settings():
    """Test settings retrieval."""
    settings = get_settings()
    assert isinstance(settings, Settings)
    assert settings.app_name == "orchestrator"


def test_settings_defaults(monkeypatch):
    """Test default settings values."""
    # Clear env vars set by conftest
    monkeypatch.delenv("ECS_CLUSTER_NAME", raising=False)
    monkeypatch.delenv("ECS_TASK_DEFINITION", raising=False)
    monkeypatch.delenv("ECS_CONTAINER_NAME", raising=False)

    # Clear cached settings
    get_settings.cache_clear()

    settings = Settings()
    assert settings.app_name == "orchestrator"
    assert settings.debug is False
    assert settings.containers_table == "openclaw-containers"
    assert settings.ecs_cluster_name == "openclaw"
    assert settings.ecs_task_definition == "openclaw-agent"
    assert settings.ecs_container_name == "openclaw-agent"
    assert settings.dynamodb_region == "us-east-1"

    # Reset cache
    get_settings.cache_clear()


def test_settings_from_env(monkeypatch):
    """Test settings loaded from environment variables."""
    monkeypatch.setenv("APP_NAME", "test-orchestrator")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("CONTAINERS_TABLE", "test-containers")

    # Clear cached settings
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.app_name == "test-orchestrator"
    assert settings.debug is True
    assert settings.containers_table == "test-containers"

    # Reset cache
    get_settings.cache_clear()
