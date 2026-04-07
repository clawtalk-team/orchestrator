"""Unit tests for authentication middleware."""
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from app.middleware.auth import APIKeyMiddleware


@pytest.fixture
def app():
    """Create test FastAPI app."""
    app = FastAPI()
    app.add_middleware(APIKeyMiddleware)
    
    @app.get("/test")
    async def test_endpoint(request: Request):
        return {"user_id": request.state.user_id}
    
    @app.get("/health")
    async def health():
        return {"status": "ok"}
    
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


def test_public_endpoints_no_auth(client):
    """Test public endpoints don't require authentication."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_protected_endpoint_no_auth(client):
    """Test protected endpoints require authentication."""
    response = client.get("/test")
    assert response.status_code == 401
    assert "Missing or invalid Authorization header" in response.json()["detail"]


def test_protected_endpoint_invalid_format(client):
    """Test protected endpoints reject invalid auth format."""
    response = client.get("/test", headers={"Authorization": "InvalidFormat"})
    assert response.status_code == 401


def test_protected_endpoint_with_master_key(client, monkeypatch):
    """Test master API key access."""
    monkeypatch.setenv("MASTER_API_KEY", "test-master-key")
    
    # Clear settings cache
    from app.config import get_settings
    get_settings.cache_clear()
    
    response = client.get("/test", headers={"Authorization": "Bearer test-master-key"})
    assert response.status_code == 200
    assert response.json()["user_id"] == "master"
    
    get_settings.cache_clear()


def test_protected_endpoint_with_user_token(client):
    """Test user token format validation."""
    response = client.get("/test", headers={"Authorization": "Bearer user-123:token-abc-def"})
    assert response.status_code == 200
    assert response.json()["user_id"] == "user-123"


def test_protected_endpoint_short_token(client):
    """Test short token rejection."""
    response = client.get("/test", headers={"Authorization": "Bearer short"})
    assert response.status_code == 401
    assert "Invalid API key" in response.json()["detail"]
