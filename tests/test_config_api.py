"""
Comprehensive test suite for /config API endpoints.

Tests CRUD operations on config records:
- User configs (named configurations per user)
- System configs (global defaults)

Tests both positive and negative scenarios with mocked auth-gateway.
"""

import json
from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from fastapi import status


class TestConfigAPIAuthentication:
    """Test authentication and authorization for config endpoints."""

    def test_get_user_config_without_auth(self, client):
        """GET /config requires authentication."""
        response = client.get("/config")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_create_user_config_without_auth(self, client):
        """POST /config requires authentication."""
        response = client.post("/config", json={"llm_provider": "anthropic"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_update_user_config_without_auth(self, client):
        """PUT /config/{config_name} requires authentication."""
        response = client.put("/config/default", json={"llm_provider": "openai"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_delete_user_config_without_auth(self, client):
        """DELETE /config/{config_name} requires authentication."""
        response = client.delete("/config/default")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestUserConfigCRUD:
    """Test CRUD operations on user configurations."""

    @patch("app.middleware.auth.get_auth_client")
    def test_list_user_configs_empty(self, mock_get_auth_client, client):
        """GET /config returns empty list when no configs exist."""
        # Mock auth-gateway response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"user_id": "test-user"}

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_auth_client.return_value = mock_client

        response = client.get(
            "/config", headers={"Authorization": "Bearer test-api-key"}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0

    @patch("app.middleware.auth.get_auth_client")
    def test_create_user_config(self, mock_get_auth_client, client):
        """POST /config creates a new user config."""
        # Mock auth-gateway response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"user_id": "test-user"}

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_auth_client.return_value = mock_client

        config_data = {
            "config_name": "default",
            "llm_provider": "anthropic",
            "openclaw_model": "claude-3-haiku-20240307",
            "anthropic_api_key": "sk-ant-test123",
            "max_containers": 5,
        }

        response = client.post(
            "/config",
            json=config_data,
            headers={"Authorization": "Bearer test-api-key"},
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["config_name"] == "default"
        assert data["llm_provider"] == "anthropic"
        assert data["openclaw_model"] == "claude-3-haiku-20240307"
        assert data["anthropic_api_key"] == "sk-ant-test123"
        assert data["max_containers"] == 5
        assert "created_at" in data
        assert "updated_at" in data

    @patch("app.middleware.auth.get_auth_client")
    def test_create_multiple_named_configs(self, mock_get_auth_client, client):
        """POST /config can create multiple named configs for same user."""
        # Mock auth-gateway response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"user_id": "test-user"}

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_auth_client.return_value = mock_client

        # Create first config
        response1 = client.post(
            "/config",
            json={
                "config_name": "production",
                "llm_provider": "anthropic",
                "anthropic_api_key": "sk-ant-prod",
            },
            headers={"Authorization": "Bearer test-api-key"},
        )
        assert response1.status_code == status.HTTP_201_CREATED

        # Create second config
        response2 = client.post(
            "/config",
            json={
                "config_name": "development",
                "llm_provider": "openai",
                "openai_api_key": "sk-openai-dev",
            },
            headers={"Authorization": "Bearer test-api-key"},
        )
        assert response2.status_code == status.HTTP_201_CREATED

        # List should show both
        response_list = client.get(
            "/config", headers={"Authorization": "Bearer test-api-key"}
        )
        assert response_list.status_code == status.HTTP_200_OK
        configs = response_list.json()
        assert len(configs) == 2
        config_names = {c["config_name"] for c in configs}
        assert config_names == {"production", "development"}

    @patch("app.middleware.auth.get_auth_client")
    def test_get_specific_user_config(self, mock_get_auth_client, client):
        """GET /config/{config_name} returns specific config."""
        # Mock auth-gateway response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"user_id": "test-user"}

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_auth_client.return_value = mock_client

        # Create config first
        client.post(
            "/config",
            json={
                "config_name": "test-config",
                "llm_provider": "anthropic",
                "custom_field": "custom_value",
            },
            headers={"Authorization": "Bearer test-api-key"},
        )

        # Get specific config
        response = client.get(
            "/config/test-config", headers={"Authorization": "Bearer test-api-key"}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["config_name"] == "test-config"
        assert data["llm_provider"] == "anthropic"
        assert data["custom_field"] == "custom_value"

    @patch("app.middleware.auth.get_auth_client")
    def test_get_nonexistent_config(self, mock_get_auth_client, client):
        """GET /config/{config_name} returns 404 for nonexistent config."""
        # Mock auth-gateway response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"user_id": "test-user"}

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_auth_client.return_value = mock_client

        response = client.get(
            "/config/nonexistent", headers={"Authorization": "Bearer test-api-key"}
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "not found" in response.json()["detail"].lower()

    @patch("app.middleware.auth.get_auth_client")
    def test_update_user_config_merge(self, mock_get_auth_client, client):
        """PUT /config/{config_name} merges with existing config."""
        # Mock auth-gateway response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"user_id": "test-user"}

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_auth_client.return_value = mock_client

        # Create initial config
        client.post(
            "/config",
            json={
                "config_name": "merge-test",
                "llm_provider": "anthropic",
                "anthropic_api_key": "sk-ant-original",
                "max_containers": 3,
            },
            headers={"Authorization": "Bearer test-api-key"},
        )

        # Update with partial data (should merge)
        response = client.put(
            "/config/merge-test",
            json={"anthropic_api_key": "sk-ant-updated", "new_field": "new_value"},
            headers={"Authorization": "Bearer test-api-key"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["llm_provider"] == "anthropic"  # Preserved
        assert data["anthropic_api_key"] == "sk-ant-updated"  # Updated
        assert data["max_containers"] == 3  # Preserved
        assert data["new_field"] == "new_value"  # Added

    @patch("app.middleware.auth.get_auth_client")
    def test_update_user_config_overwrite(self, mock_get_auth_client, client):
        """PUT /config/{config_name}?overwrite=true replaces entire config."""
        # Mock auth-gateway response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"user_id": "test-user"}

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_auth_client.return_value = mock_client

        # Create initial config
        client.post(
            "/config",
            json={
                "config_name": "overwrite-test",
                "llm_provider": "anthropic",
                "anthropic_api_key": "sk-ant-original",
                "max_containers": 3,
            },
            headers={"Authorization": "Bearer test-api-key"},
        )

        # Update with overwrite=true (should replace)
        response = client.put(
            "/config/overwrite-test?overwrite=true",
            json={"llm_provider": "openai", "openai_api_key": "sk-openai-new"},
            headers={"Authorization": "Bearer test-api-key"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["llm_provider"] == "openai"
        assert data["openai_api_key"] == "sk-openai-new"
        assert "anthropic_api_key" not in data  # Removed
        assert "max_containers" not in data  # Removed

    @patch("app.middleware.auth.get_auth_client")
    def test_update_nonexistent_config_creates_new(self, mock_get_auth_client, client):
        """PUT /config/{config_name} creates new config if doesn't exist."""
        # Mock auth-gateway response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"user_id": "test-user"}

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_auth_client.return_value = mock_client

        response = client.put(
            "/config/new-config",
            json={"llm_provider": "anthropic", "anthropic_api_key": "sk-ant-new"},
            headers={"Authorization": "Bearer test-api-key"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["config_name"] == "new-config"
        assert data["llm_provider"] == "anthropic"

    @patch("app.middleware.auth.get_auth_client")
    def test_delete_user_config(self, mock_get_auth_client, client):
        """DELETE /config/{config_name} removes config."""
        # Mock auth-gateway response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"user_id": "test-user"}

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_auth_client.return_value = mock_client

        # Create config first
        client.post(
            "/config",
            json={"config_name": "to-delete", "llm_provider": "anthropic"},
            headers={"Authorization": "Bearer test-api-key"},
        )

        # Delete it
        response = client.delete(
            "/config/to-delete", headers={"Authorization": "Bearer test-api-key"}
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

        # Verify it's gone
        get_response = client.get(
            "/config/to-delete", headers={"Authorization": "Bearer test-api-key"}
        )
        assert get_response.status_code == status.HTTP_404_NOT_FOUND

    @patch("app.middleware.auth.get_auth_client")
    def test_delete_nonexistent_config(self, mock_get_auth_client, client):
        """DELETE /config/{config_name} returns 404 for nonexistent config."""
        # Mock auth-gateway response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"user_id": "test-user"}

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_auth_client.return_value = mock_client

        response = client.delete(
            "/config/nonexistent", headers={"Authorization": "Bearer test-api-key"}
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestConfigExtensibility:
    """Test that configs support arbitrary JSON fields."""

    @patch("app.middleware.auth.get_auth_client")
    def test_config_accepts_arbitrary_fields(self, mock_get_auth_client, client):
        """Config accepts and stores arbitrary JSON fields."""
        # Mock auth-gateway response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"user_id": "test-user"}

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_auth_client.return_value = mock_client

        config_data = {
            "config_name": "custom",
            "standard_field": "value1",
            "custom_string": "custom_value",
            "custom_number": 42,
            "custom_boolean": True,
            "custom_array": [1, 2, 3],
            "custom_object": {"nested": "value"},
        }

        response = client.post(
            "/config",
            json=config_data,
            headers={"Authorization": "Bearer test-api-key"},
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["custom_string"] == "custom_value"
        assert data["custom_number"] == 42
        assert data["custom_boolean"] is True
        assert data["custom_array"] == [1, 2, 3]
        assert data["custom_object"] == {"nested": "value"}


class TestSystemConfig:
    """Test system configuration endpoints (admin only)."""

    @patch("app.middleware.auth.get_auth_client")
    def test_get_system_config(self, mock_get_auth_client, client, monkeypatch):
        """GET /config/system returns system defaults."""
        # Set master API key
        monkeypatch.setenv("MASTER_API_KEY", "master-key-123")

        # Clear settings cache to pick up new env var
        from app.config import get_settings

        get_settings.cache_clear()

        # Mock auth-gateway response (won't be called due to master key)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"user_id": "admin"}

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_auth_client.return_value = mock_client

        response = client.get(
            "/config/system", headers={"Authorization": "Bearer master-key-123"}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "auth_gateway_url" in data
        assert "openclaw_url" in data
        assert "voice_gateway_url" in data

        # Clean up
        get_settings.cache_clear()

    @patch("app.middleware.auth.get_auth_client")
    def test_get_system_config_non_admin(
        self, mock_get_auth_client, client, monkeypatch
    ):
        """GET /config/system requires admin access."""
        # Ensure no master key is set
        monkeypatch.delenv("MASTER_API_KEY", raising=False)

        # Clear settings cache
        from app.config import get_settings

        get_settings.cache_clear()

        # Mock auth-gateway response for regular user
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"user_id": "regular-user"}

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_auth_client.return_value = mock_client

        response = client.get(
            "/config/system", headers={"Authorization": "Bearer regular-api-key"}
        )

        # Should return 403 Forbidden for non-admin users
        assert response.status_code == status.HTTP_403_FORBIDDEN

        # Clean up
        get_settings.cache_clear()

    @patch("app.middleware.auth.get_auth_client")
    def test_update_system_config(self, mock_get_auth_client, client, monkeypatch):
        """PUT /config/system updates system defaults."""
        # Set master API key
        monkeypatch.setenv("MASTER_API_KEY", "master-key-123")

        # Clear settings cache
        from app.config import get_settings

        get_settings.cache_clear()

        # Mock auth-gateway response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"user_id": "admin"}

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_auth_client.return_value = mock_client

        system_config = {
            "auth_gateway_url": "http://auth.example.com",
            "openclaw_url": "http://openclaw.example.com",
            "voice_gateway_url": "ws://voice.example.com",
        }

        response = client.put(
            "/config/system",
            json=system_config,
            headers={"Authorization": "Bearer master-key-123"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["auth_gateway_url"] == "http://auth.example.com"
        assert data["openclaw_url"] == "http://openclaw.example.com"

        # Clean up
        get_settings.cache_clear()

    @patch("app.middleware.auth.get_auth_client")
    def test_update_system_config_non_admin(
        self, mock_get_auth_client, client, monkeypatch
    ):
        """PUT /config/system requires admin access."""
        # Ensure no master key is set
        monkeypatch.delenv("MASTER_API_KEY", raising=False)

        # Clear settings cache
        from app.config import get_settings

        get_settings.cache_clear()

        # Mock auth-gateway response for regular user
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"user_id": "regular-user"}

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_auth_client.return_value = mock_client

        response = client.put(
            "/config/system",
            json={"auth_gateway_url": "http://malicious.com"},
            headers={"Authorization": "Bearer regular-api-key"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

        # Clean up
        get_settings.cache_clear()


class TestConfigValidation:
    """Test validation and error handling."""

    @patch("app.middleware.auth.get_auth_client")
    def test_create_config_missing_config_name(self, mock_get_auth_client, client):
        """POST /config requires config_name."""
        # Mock auth-gateway response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"user_id": "test-user"}

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_auth_client.return_value = mock_client

        response = client.post(
            "/config",
            json={"llm_provider": "anthropic"},  # Missing config_name
            headers={"Authorization": "Bearer test-api-key"},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @patch("app.middleware.auth.get_auth_client")
    def test_create_config_invalid_json(self, mock_get_auth_client, client):
        """POST /config validates JSON structure."""
        # Mock auth-gateway response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"user_id": "test-user"}

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_auth_client.return_value = mock_client

        response = client.post(
            "/config",
            data="invalid-json",  # Not valid JSON
            headers={
                "Authorization": "Bearer test-api-key",
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


class TestConfigIsolation:
    """Test that users can only access their own configs."""

    @patch("app.middleware.auth.get_auth_client")
    def test_user_cannot_see_other_users_configs(self, mock_get_auth_client, client):
        """Users can only see their own configs."""

        # Set up mock to return different user_id based on the API key
        def mock_auth_response(*args, **kwargs):
            # Check which authorization header was used
            auth_header = kwargs.get("headers", {}).get("Authorization", "")

            response = MagicMock()
            response.status_code = 200

            if "user1-key" in auth_header:
                response.json.return_value = {"user_id": "user1"}
            elif "user2-key" in auth_header:
                response.json.return_value = {"user_id": "user2"}
            else:
                response.json.return_value = {"user_id": "unknown"}

            return response

        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=mock_auth_response)
        mock_get_auth_client.return_value = mock_client

        # Create config for user1
        client.post(
            "/config",
            json={"config_name": "user1-config", "llm_provider": "anthropic"},
            headers={"Authorization": "Bearer user1-key"},
        )

        # Try to list configs as user2
        response = client.get("/config", headers={"Authorization": "Bearer user2-key"})

        assert response.status_code == status.HTTP_200_OK
        configs = response.json()
        # user2 should see no configs (user1's config is isolated)
        assert len(configs) == 0

    @patch("app.middleware.auth.get_auth_client")
    def test_user_cannot_access_other_users_specific_config(
        self, mock_get_auth_client, client
    ):
        """Users cannot access other users' configs by name."""

        # Set up mock to return different user_id based on the API key
        def mock_auth_response(*args, **kwargs):
            auth_header = kwargs.get("headers", {}).get("Authorization", "")

            response = MagicMock()
            response.status_code = 200

            if "user1-key" in auth_header:
                response.json.return_value = {"user_id": "user1"}
            elif "user2-key" in auth_header:
                response.json.return_value = {"user_id": "user2"}
            else:
                response.json.return_value = {"user_id": "unknown"}

            return response

        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=mock_auth_response)
        mock_get_auth_client.return_value = mock_client

        # Create config for user1
        client.post(
            "/config",
            json={"config_name": "private-config", "secret": "sensitive"},
            headers={"Authorization": "Bearer user1-key"},
        )

        # Try to access as user2
        response = client.get(
            "/config/private-config", headers={"Authorization": "Bearer user2-key"}
        )

        # Should return 404 (not found from user2's perspective)
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestConfigBackwardCompatibility:
    """Test backward compatibility with CONFIG#primary pattern."""

    @patch("app.middleware.auth.get_auth_client")
    def test_default_config_fallback_to_primary(self, mock_get_auth_client, client):
        """GET /config/default falls back to CONFIG#primary for backward compatibility."""
        # This test ensures that if a user has an old CONFIG#primary record,
        # they can still access it via the 'default' name
        # This is handled by the UserConfigService internally

        # Mock auth-gateway response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"user_id": "legacy-user"}

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_auth_client.return_value = mock_client

        # Manually create a CONFIG#primary record in DynamoDB
        from app.services.dynamodb import _get_table
        from datetime import datetime, timezone

        table = _get_table()
        table.put_item(
            Item={
                "pk": "USER#legacy-user",
                "sk": "CONFIG#primary",  # Old pattern
                "config_type": "user_config",
                "user_id": "legacy-user",
                "llm_provider": "anthropic",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

        # Access via 'default' name should find the primary config
        response = client.get(
            "/config/default", headers={"Authorization": "Bearer legacy-key"}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["llm_provider"] == "anthropic"


class TestConfigMerge:
    """Test configuration merge behavior for containers."""

    @patch("app.middleware.auth.get_auth_client")
    def test_get_config_merged_by_default(self, mock_get_auth_client, client):
        """GET /config/{config_name} merges with system config by default."""
        # Mock auth-gateway response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"user_id": "test-user"}

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_auth_client.return_value = mock_client

        # Create system config
        from app.services.user_config import UserConfigService
        config_service = UserConfigService()
        config_service.save_system_config({
            "auth_gateway_url": "https://auth.example.com",
            "openclaw_url": "http://localhost:18789",
            "openclaw_token": "test-token-123",
            "voice_gateway_url": "ws://voice.example.com",
        })

        # Create user config
        client.post(
            "/config",
            json={
                "config_name": "default",
                "llm_provider": "anthropic",
                "anthropic_api_key": "sk-ant-test123",
                "auth_gateway_api_key": "user-api-key",
            },
            headers={"Authorization": "Bearer test-api-key"},
        )

        # Get merged config (default behavior)
        response = client.get(
            "/config/default",
            headers={"Authorization": "Bearer test-api-key"}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Verify user config fields present
        assert data["llm_provider"] == "anthropic"
        assert data["anthropic_api_key"] == "sk-ant-test123"
        assert data["auth_gateway_api_key"] == "user-api-key"

        # Verify system config fields present
        assert data["auth_gateway_url"] == "https://auth.example.com"
        assert data["openclaw_url"] == "http://localhost:18789"
        assert data["openclaw_token"] == "test-token-123"
        assert data["voice_gateway_url"] == "ws://voice.example.com"

    @patch("app.middleware.auth.get_auth_client")
    def test_get_config_merged_true_explicit(self, mock_get_auth_client, client):
        """GET /config/{config_name}?merged=true explicitly requests merge."""
        # Mock auth-gateway response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"user_id": "test-user"}

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_auth_client.return_value = mock_client

        # Create system config
        from app.services.user_config import UserConfigService
        config_service = UserConfigService()
        config_service.save_system_config({
            "auth_gateway_url": "https://auth.example.com",
            "openclaw_url": "http://localhost:18789",
            "openclaw_token": "test-token-123",
        })

        # Create user config
        client.post(
            "/config",
            json={
                "config_name": "default",
                "llm_provider": "anthropic",
            },
            headers={"Authorization": "Bearer test-api-key"},
        )

        # Get merged config explicitly
        response = client.get(
            "/config/default?merged=true",
            headers={"Authorization": "Bearer test-api-key"}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Verify merged config has both user and system fields
        assert data["llm_provider"] == "anthropic"
        assert data["auth_gateway_url"] == "https://auth.example.com"
        assert data["openclaw_url"] == "http://localhost:18789"
        assert data["openclaw_token"] == "test-token-123"

    @patch("app.middleware.auth.get_auth_client")
    def test_get_config_unmerged(self, mock_get_auth_client, client):
        """GET /config/{config_name}?merged=false returns only user config."""
        # Mock auth-gateway response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"user_id": "test-user"}

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_auth_client.return_value = mock_client

        # Create system config
        from app.services.user_config import UserConfigService
        config_service = UserConfigService()
        config_service.save_system_config({
            "auth_gateway_url": "https://auth.example.com",
            "openclaw_url": "http://localhost:18789",
            "openclaw_token": "test-token-123",
        })

        # Create user config
        client.post(
            "/config",
            json={
                "config_name": "default",
                "llm_provider": "anthropic",
                "anthropic_api_key": "sk-ant-test123",
            },
            headers={"Authorization": "Bearer test-api-key"},
        )

        # Get unmerged config (user config only)
        response = client.get(
            "/config/default?merged=false",
            headers={"Authorization": "Bearer test-api-key"}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # Verify user config fields present
        assert data["llm_provider"] == "anthropic"
        assert data["anthropic_api_key"] == "sk-ant-test123"

        # Verify system config fields NOT present
        assert "auth_gateway_url" not in data
        assert "openclaw_url" not in data
        assert "openclaw_token" not in data

    @patch("app.middleware.auth.get_auth_client")
    def test_merged_config_user_overrides_system(self, mock_get_auth_client, client):
        """User config values override system config values when merged."""
        # Mock auth-gateway response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"user_id": "test-user"}

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_get_auth_client.return_value = mock_client

        # Create system config with openclaw_token
        from app.services.user_config import UserConfigService
        config_service = UserConfigService()
        config_service.save_system_config({
            "auth_gateway_url": "https://auth.example.com",
            "openclaw_token": "system-token-123",
        })

        # Create user config that overrides openclaw_token
        client.post(
            "/config",
            json={
                "config_name": "default",
                "llm_provider": "anthropic",
                "openclaw_token": "user-token-456",  # Override system value
            },
            headers={"Authorization": "Bearer test-api-key"},
        )

        # Get merged config
        response = client.get(
            "/config/default",
            headers={"Authorization": "Bearer test-api-key"}
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        # User value should override system value
        assert data["openclaw_token"] == "user-token-456"
        # System values not overridden should be present
        assert data["auth_gateway_url"] == "https://auth.example.com"
