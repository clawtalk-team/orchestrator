"""Integration tests for git SHA in health endpoint."""

import os
from unittest.mock import patch

import pytest


def test_health_endpoint_with_git_commit(client):
    """Test health endpoint returns git_sha when GIT_COMMIT env var is set."""
    with patch.dict(os.environ, {"GIT_COMMIT": "abc1234"}):
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "orchestrator"
        assert data["git_sha"] == "abc1234"


def test_health_endpoint_without_git_commit(client):
    """Test health endpoint returns null git_sha when GIT_COMMIT is not set."""
    # Remove GIT_COMMIT from environment if present
    with patch.dict(os.environ, {}, clear=True):
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "orchestrator"
        assert data["git_sha"] is None


def test_health_endpoint_with_unknown_git_commit(client):
    """Test health endpoint returns null when GIT_COMMIT is 'unknown' (build default)."""
    with patch.dict(os.environ, {"GIT_COMMIT": "unknown"}):
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "orchestrator"
        assert data["git_sha"] is None


def test_health_endpoint_with_empty_git_commit(client):
    """Test health endpoint returns null when GIT_COMMIT is empty."""
    with patch.dict(os.environ, {"GIT_COMMIT": ""}):
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "orchestrator"
        assert data["git_sha"] is None


def test_health_endpoint_with_whitespace_git_commit(client):
    """Test health endpoint trims whitespace from GIT_COMMIT."""
    with patch.dict(os.environ, {"GIT_COMMIT": "  abc1234  "}):
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "orchestrator"
        assert data["git_sha"] == "abc1234"
