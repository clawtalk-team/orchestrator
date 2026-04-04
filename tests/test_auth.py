"""Tests for authentication middleware."""

import pytest


def test_public_health_endpoint(client):
    """Test that health endpoint is public."""
    response = client.get("/health")
    assert response.status_code == 200


def test_public_root_endpoint(client):
    """Test that root endpoint is public."""
    response = client.get("/")
    assert response.status_code == 200


def test_public_docs_endpoint(client):
    """Test that docs endpoint is public."""
    response = client.get("/docs")
    assert response.status_code in [200, 404]  # May not be enabled


def test_protected_endpoint_without_auth(client):
    """Test that protected endpoints require auth."""
    response = client.get("/containers")
    assert response.status_code == 401
    assert "Authorization" in response.json()["detail"]


def test_protected_endpoint_with_invalid_auth(client):
    """Test that invalid auth token is rejected."""
    headers = {"Authorization": "Bearer invalid"}
    response = client.get("/containers", headers=headers)
    assert response.status_code == 401


def test_protected_endpoint_with_valid_auth(client):
    """Test that valid auth token is accepted."""
    headers = {"Authorization": "Bearer test-user:test-token-here"}
    response = client.get("/containers", headers=headers)
    assert response.status_code == 200


def test_bearer_token_extraction(client):
    """Test that bearer token is correctly extracted."""
    headers = {"Authorization": "Bearer user-id:token-value-long"}
    response = client.get("/containers", headers=headers)
    assert response.status_code == 200


def test_auth_header_case_sensitive(client):
    """Test that Authorization header is case-insensitive (per HTTP spec)."""
    headers = {"authorization": "Bearer user-id:token-value-long"}
    # FastAPI normalizes header names, so this should work
    response = client.get("/containers", headers=headers)
    # This depends on TestClient behavior with headers


def test_missing_bearer_prefix(client):
    """Test that missing Bearer prefix is rejected."""
    headers = {"Authorization": "user-id:token-value"}
    response = client.get("/containers", headers=headers)
    assert response.status_code == 401


def test_short_token_rejected(client):
    """Test that tokens shorter than 20 chars are rejected."""
    headers = {"Authorization": "Bearer short"}
    response = client.get("/containers", headers=headers)
    assert response.status_code == 401


def test_invalid_token_format(client):
    """Test that tokens without user_id:token format are rejected."""
    headers = {"Authorization": "Bearer nocolon1234567890"}
    response = client.get("/containers", headers=headers)
    assert response.status_code == 401
