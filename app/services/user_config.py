"""
User configuration service for managing per-user configs in DynamoDB.

Stores two types of configs:
1. OpenClaw config (openclaw.json) - for OpenClaw gateway
2. Agent config (clawtalk.json) - for openclaw-agent

Both stored in the same DynamoDB table using single-table design:
- pk: USER#{user_id}, sk: CONFIG#primary - Main user config
- pk: SYSTEM, sk: CONFIG#defaults - System-wide defaults
"""

from typing import Optional, Dict, Any
from datetime import datetime
import json

from app.services.dynamodb import _get_table
from app.services.encryption import get_encryptor


class UserConfigService:
    """Service for managing user configurations."""

    def __init__(self):
        self.table = _get_table()
        self.encryptor = get_encryptor()

    def get_user_config(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get user's configuration with decrypted secrets.

        Args:
            user_id: The user ID

        Returns:
            Dict containing user config, or None if not found
        """
        response = self.table.get_item(
            Key={"pk": f"USER#{user_id}", "sk": "CONFIG#primary"}
        )

        if "Item" not in response:
            return None

        item = response["Item"]
        config = {}

        # Copy non-secret fields
        for key in [
            "user_id",
            "llm_provider",
            "openclaw_model",
            "max_containers",
        ]:
            if key in item:
                config[key] = item[key]

        # Decrypt secrets
        if "auth_gateway_api_key_encrypted" in item:
            config["auth_gateway_api_key"] = self.encryptor.decrypt(
                item["auth_gateway_api_key_encrypted"]
            )

        if "anthropic_api_key_encrypted" in item:
            config["anthropic_api_key"] = self.encryptor.decrypt(
                item["anthropic_api_key_encrypted"]
            )

        if "openai_api_key_encrypted" in item:
            config["openai_api_key"] = self.encryptor.decrypt(
                item["openai_api_key_encrypted"]
            )

        if "openrouter_api_key_encrypted" in item:
            config["openrouter_api_key"] = self.encryptor.decrypt(
                item["openrouter_api_key_encrypted"]
            )

        if "openclaw_token_encrypted" in item:
            config["openclaw_token"] = self.encryptor.decrypt(
                item["openclaw_token_encrypted"]
            )

        return config

    def save_user_config(
        self, user_id: str, config: Dict[str, Any], overwrite: bool = False
    ) -> None:
        """
        Save user configuration with encrypted secrets.

        Args:
            user_id: The user ID
            config: Configuration dict with secrets in plaintext
            overwrite: If False, merge with existing config; if True, replace completely
        """
        now = datetime.utcnow()

        # If not overwriting, merge with existing config
        if not overwrite:
            existing = self.get_user_config(user_id) or {}
            # Merge: new values override old ones
            merged = {**existing, **config}
            config = merged

        item = {
            "pk": f"USER#{user_id}",
            "sk": "CONFIG#primary",
            "config_type": "user_config",
            "user_id": user_id,
            "updated_at": now.isoformat(),
        }

        # Encrypt secrets
        secret_fields = [
            "auth_gateway_api_key",
            "anthropic_api_key",
            "openai_api_key",
            "openrouter_api_key",
            "openclaw_token",
        ]

        for field in secret_fields:
            if field in config and config[field]:
                item[f"{field}_encrypted"] = self.encryptor.encrypt(config[field])

        # Store non-secret fields
        non_secret_fields = [
            "llm_provider",
            "openclaw_model",
            "max_containers",
        ]

        for field in non_secret_fields:
            if field in config:
                item[field] = config[field]

        # Check if exists to preserve created_at
        existing_item = self.table.get_item(
            Key={"pk": f"USER#{user_id}", "sk": "CONFIG#primary"}
        )
        if "Item" in existing_item:
            item["created_at"] = existing_item["Item"].get(
                "created_at", now.isoformat()
            )
        else:
            item["created_at"] = now.isoformat()

        self.table.put_item(Item=item)

    def get_system_config(self) -> Dict[str, Any]:
        """
        Get system-wide configuration.

        Returns:
            Dict containing system config (URLs, defaults, etc.)
        """
        response = self.table.get_item(
            Key={"pk": "SYSTEM", "sk": "CONFIG#defaults"}
        )

        if "Item" not in response:
            # Return defaults if not found
            from app.config import get_settings

            settings = get_settings()
            return {
                "auth_gateway_url": settings.auth_gateway_url or "http://localhost:8001",
                "openclaw_url": "http://localhost:18789",
                "voice_gateway_url": "ws://localhost:9090",
            }

        item = response["Item"]
        return {
            "auth_gateway_url": item.get("auth_gateway_url"),
            "openclaw_url": item.get("openclaw_url"),
            "openclaw_token": item.get("openclaw_token"),
            "voice_gateway_url": item.get("voice_gateway_url"),
        }

    def save_system_config(self, config: Dict[str, Any]) -> None:
        """
        Save system-wide configuration.

        Args:
            config: System configuration (URLs, tokens, etc.)
        """
        now = datetime.utcnow()

        item = {
            "pk": "SYSTEM",
            "sk": "CONFIG#defaults",
            "config_type": "system_config",
            "updated_at": now.isoformat(),
        }

        # Store system fields
        system_fields = [
            "auth_gateway_url",
            "openclaw_url",
            "openclaw_token",
            "voice_gateway_url",
        ]

        for field in system_fields:
            if field in config:
                item[field] = config[field]

        self.table.put_item(Item=item)

    def build_openclaw_config(self, user_id: str) -> Dict[str, Any]:
        """
        Build OpenClaw gateway config (openclaw.json).

        This is the config for the OpenClaw gateway service, which handles
        LLM inference. It needs provider API keys.

        Args:
            user_id: The user ID

        Returns:
            Dict suitable for openclaw.json
        """
        user_config = self.get_user_config(user_id) or {}
        system_config = self.get_system_config()

        llm_provider = user_config.get("llm_provider", "anthropic")

        # Build provider config based on LLM provider
        providers = {}

        if llm_provider == "openrouter" and user_config.get("openrouter_api_key"):
            providers["openrouter"] = {
                "baseUrl": "https://openrouter.ai/api/v1",
                "apiKey": user_config["openrouter_api_key"],
                "api": "openai-completions",
                "models": [
                    {
                        "id": "anthropic/claude-haiku-4.5",
                        "name": "Claude Haiku 4.5 (OpenRouter)",
                        "api": "openai-completions",
                        "input": ["text"],
                        "cost": {
                            "input": 0.0008,
                            "output": 0.004,
                            "cacheRead": 0,
                            "cacheWrite": 0,
                        },
                        "contextWindow": 200000,
                        "maxTokens": 8192,
                    }
                ],
            }
        elif llm_provider == "anthropic" and user_config.get("anthropic_api_key"):
            providers["anthropic"] = {
                "apiKey": user_config["anthropic_api_key"],
                "models": [
                    {
                        "id": "claude-3-haiku-20240307",
                        "name": "Claude 3 Haiku",
                    }
                ],
            }
        elif llm_provider == "openai" and user_config.get("openai_api_key"):
            providers["openai"] = {
                "apiKey": user_config["openai_api_key"],
                "models": [{"id": "gpt-4", "name": "GPT-4"}],
            }

        return {
            "gateway": {
                "port": 18789,
                "mode": "local",
                "bind": "lan",
                "auth": {"mode": "token", "token": "test-token-123"},
                "http": {"endpoints": {"chatCompletions": {"enabled": True}}},
            },
            "models": {"providers": providers},
            "agents": {
                "defaults": {
                    "model": {
                        "primary": f"{llm_provider}/{user_config.get('openclaw_model', 'claude-3-haiku-20240307')}"
                    }
                }
            },
        }

    def build_agent_config(self, user_id: str, api_key: str) -> Dict[str, Any]:
        """
        Build openclaw-agent config (clawtalk.json).

        This is the config for the openclaw-agent service, which manages
        voice agents. It needs auth gateway credentials.

        Args:
            user_id: The user ID
            api_key: The API key (from Authorization header)

        Returns:
            Dict suitable for clawtalk.json
        """
        user_config = self.get_user_config(user_id) or {}
        system_config = self.get_system_config()

        return {
            "agents": [],  # Will be populated after registration
            "user_id": user_id,
            "auth_gateway_url": system_config.get("auth_gateway_url"),
            "auth_gateway_api_key": api_key,
            "openclaw_url": system_config.get("openclaw_url"),
            "openclaw_token": system_config.get("openclaw_token", "test-token-123"),
            "openclaw_model": user_config.get(
                "openclaw_model", "claude-3-haiku-20240307"
            ),
            "llm_provider": user_config.get("llm_provider", "anthropic"),
            "anthropic_api_key": user_config.get("anthropic_api_key", ""),
            "openai_api_key": user_config.get("openai_api_key", ""),
        }

    def build_container_configs(
        self, user_id: str, api_key: str
    ) -> Dict[str, Dict[str, Any]]:
        """
        Build both configs needed for a container.

        Args:
            user_id: The user ID
            api_key: The API key (from Authorization header)

        Returns:
            Dict with keys "openclaw" and "agent" containing respective configs
        """
        return {
            "openclaw": self.build_openclaw_config(user_id),
            "agent": self.build_agent_config(user_id, api_key),
        }
