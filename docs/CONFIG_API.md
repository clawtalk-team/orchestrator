# Configuration API Reference

This document provides detailed specifications for the Configuration API endpoints.

## Table of Contents

- [Overview](#overview)
- [Configuration Parameters](#configuration-parameters)
- [API Endpoints](#api-endpoints)
  - [User Configuration](#user-configuration)
  - [System Configuration](#system-configuration)
- [Examples](#examples)

## Overview

The Configuration API allows users and administrators to manage configuration settings stored in DynamoDB. The API uses a two-tier system:

- **System Config** - Infrastructure-wide settings (URLs, shared tokens) managed by administrators
- **User Config** - User-specific settings (API keys, preferences) managed by individual users

### Authentication

All configuration endpoints require authentication via the `Authorization` header:

```
Authorization: Bearer {USER_ID}:{TOKEN}
```

System configuration endpoints additionally require admin privileges.

## Configuration Parameters

### System Configuration Parameters

System configs are shared across all users and define infrastructure settings.

| Parameter | Type | Required | Description | Example |
|-----------|------|----------|-------------|---------|
| `auth_gateway_url` | string | Yes | Auth gateway endpoint URL | `https://your-auth-gateway.execute-api.your-region.amazonaws.com` |
| `openclaw_url` | string | Yes | OpenClaw gateway URL | `http://localhost:18789` |
| `openclaw_token` | string | Yes | Shared OpenClaw service token | `test-token-123` |
| `voice_gateway_url` | string | No | Voice gateway WebSocket URL | `ws://localhost:9090` |

**Storage:** `pk="SYSTEM"`, `sk="CONFIG#defaults"`

### User Configuration Parameters

User configs are specific to each user and define personal settings.

| Parameter | Type | Required | Description | Example |
|-----------|------|----------|-------------|---------|
| `llm_provider` | string | Yes | LLM provider choice | `anthropic`, `openai`, `openrouter` |
| `openclaw_model` | string | Yes | Default model to use | `claude-3-haiku-20240307`, `gpt-4` |
| `auth_gateway_api_key` | string | Yes | User's auth gateway API key | `b13b7bb9cbe9ecfa112cf...` |
| `anthropic_api_key` | string | Conditional | Anthropic API key (required if provider=anthropic) | `sk-ant-api03-...` |
| `openai_api_key` | string | Conditional | OpenAI API key (required if provider=openai) | `sk-...` |
| `openrouter_api_key` | string | Conditional | OpenRouter API key (required if provider=openrouter) | `sk-or-...` |

**Storage:** `pk="USER#{user_id}"`, `sk="CONFIG#{config_name}"`

**Note:** This parameter list will expand as new features are added. The API supports arbitrary JSON fields beyond these predefined parameters.

## API Endpoints

### User Configuration

#### List User Configurations

Get all configurations for the authenticated user.

**Request:**
```http
GET /config
Authorization: Bearer {USER_ID}:{TOKEN}
```

**Response:**
```json
{
  "configs": [
    {
      "config_name": "default",
      "llm_provider": "anthropic",
      "openclaw_model": "claude-3-haiku-20240307",
      "created_at": "2026-04-08T04:39:37.505122",
      "updated_at": "2026-04-08T04:39:37.505146"
    },
    {
      "config_name": "production",
      "llm_provider": "openai",
      "openclaw_model": "gpt-4",
      "created_at": "2026-04-08T05:00:00.000000",
      "updated_at": "2026-04-08T05:00:00.000000"
    }
  ]
}
```

**Notes:**
- API keys are excluded from list responses for security
- Only shows configurations owned by the authenticated user

---

#### Create User Configuration

Create a new named configuration.

**Request:**
```http
POST /config
Authorization: Bearer {USER_ID}:{TOKEN}
Content-Type: application/json

{
  "config_name": "default",
  "llm_provider": "anthropic",
  "anthropic_api_key": "sk-ant-api03-...",
  "openclaw_model": "claude-3-haiku-20240307",
  "auth_gateway_api_key": "b13b7bb9cbe9ecfa112cf..."
}
```

**Response:**
```json
{
  "message": "Configuration created",
  "config_name": "default",
  "created_at": "2026-04-08T04:39:37.505122",
  "updated_at": "2026-04-08T04:39:37.505146"
}
```

**Error Responses:**
- `409 Conflict` - Configuration with that name already exists
- `400 Bad Request` - Missing required fields

---

#### Get User Configuration

Retrieve a specific configuration by name.

**Request:**
```http
GET /config/{config_name}
Authorization: Bearer {USER_ID}:{TOKEN}
```

**Response:**
```json
{
  "config_name": "default",
  "user_id": "d529181f-0941-4708-a3a8-3b2fa4358c06",
  "llm_provider": "anthropic",
  "openclaw_model": "claude-3-haiku-20240307",
  "auth_gateway_api_key": "b13b7bb9cbe9ecfa112cf...",
  "anthropic_api_key": "sk-ant-api03-...",
  "created_at": "2026-04-08T04:39:37.505122",
  "updated_at": "2026-04-08T04:39:37.505146"
}
```

**Error Responses:**
- `404 Not Found` - Configuration does not exist

---

#### Update User Configuration

Update an existing configuration. Supports both merge and overwrite modes.

**Request (Merge Mode - default):**
```http
PUT /config/{config_name}
Authorization: Bearer {USER_ID}:{TOKEN}
Content-Type: application/json

{
  "openclaw_model": "claude-3-opus-20240229"
}
```

**Request (Overwrite Mode):**
```http
PUT /config/{config_name}?overwrite=true
Authorization: Bearer {USER_ID}:{TOKEN}
Content-Type: application/json

{
  "llm_provider": "openai",
  "openai_api_key": "sk-...",
  "openclaw_model": "gpt-4",
  "auth_gateway_api_key": "b13b7bb9cbe9ecfa112cf..."
}
```

**Response:**
```json
{
  "message": "Configuration updated",
  "config_name": "default",
  "created_at": "2026-04-08T04:39:37.505122",
  "updated_at": "2026-04-08T06:00:00.000000"
}
```

**Query Parameters:**
- `overwrite` (boolean, default: false) - If true, replaces entire config; if false, merges with existing

**Error Responses:**
- `404 Not Found` - Configuration does not exist
- `400 Bad Request` - Invalid parameters

---

#### Delete User Configuration

Delete a configuration by name.

**Request:**
```http
DELETE /config/{config_name}
Authorization: Bearer {USER_ID}:{TOKEN}
```

**Response:**
```json
{
  "message": "Configuration deleted",
  "config_name": "testing"
}
```

**Error Responses:**
- `404 Not Found` - Configuration does not exist

**Warning:** Cannot delete the "default" configuration if it's the only one.

---

### System Configuration

System configuration endpoints require admin privileges.

#### Get System Configuration

Retrieve system-wide configuration.

**Request:**
```http
GET /config/system
Authorization: Bearer {ADMIN_TOKEN}
```

**Response:**
```json
{
  "auth_gateway_url": "https://your-auth-gateway.execute-api.your-region.amazonaws.com",
  "openclaw_url": "http://localhost:18789",
  "openclaw_token": "test-token-123",
  "voice_gateway_url": "ws://localhost:9090",
  "updated_at": "2026-04-08T04:39:37.256064"
}
```

**Error Responses:**
- `403 Forbidden` - User is not an admin
- `404 Not Found` - System config not initialized

---

#### Update System Configuration

Update system-wide configuration.

**Request:**
```http
PUT /config/system
Authorization: Bearer {ADMIN_TOKEN}
Content-Type: application/json

{
  "auth_gateway_url": "https://new-auth-gateway.example.com",
  "openclaw_url": "http://localhost:18789",
  "openclaw_token": "new-token-456",
  "voice_gateway_url": "ws://new-voice-gateway:9090"
}
```

**Response:**
```json
{
  "message": "System configuration updated",
  "updated_at": "2026-04-08T07:00:00.000000"
}
```

**Error Responses:**
- `403 Forbidden` - User is not an admin
- `400 Bad Request` - Missing required fields

**Notes:**
- System config updates affect all users immediately
- Use with caution as it impacts the entire infrastructure

## Examples

### Complete Setup Workflow

#### 1. Initialize System Configuration (Admin)

```bash
curl -X PUT https://your-api-id.execute-api.your-region.amazonaws.com/config/system \
  -H "Authorization: Bearer {ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "auth_gateway_url": "https://your-auth-gateway.execute-api.your-region.amazonaws.com",
    "openclaw_url": "http://localhost:18789",
    "openclaw_token": "test-token-123",
    "voice_gateway_url": "ws://localhost:9090"
  }'
```

#### 2. Create User Configuration

```bash
curl -X POST https://your-api-id.execute-api.your-region.amazonaws.com/config \
  -H "Authorization: Bearer {USER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "config_name": "default",
    "llm_provider": "anthropic",
    "anthropic_api_key": "sk-ant-api03-YOUR-KEY",
    "openclaw_model": "claude-3-haiku-20240307",
    "auth_gateway_api_key": "b13b7bb9cbe9ecfa112cf..."
  }'
```

#### 3. Create Container Using Config

```bash
curl -X POST https://your-api-id.execute-api.your-region.amazonaws.com/containers \
  -H "Authorization: Bearer {USER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "config_name": "default"
  }'
```

### Multiple Named Configurations

#### Create Production Config
```bash
curl -X POST .../config \
  -H "Authorization: Bearer {USER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "config_name": "production",
    "llm_provider": "anthropic",
    "anthropic_api_key": "sk-ant-prod-...",
    "openclaw_model": "claude-3-opus-20240229"
  }'
```

#### Create Testing Config
```bash
curl -X POST .../config \
  -H "Authorization: Bearer {USER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "config_name": "testing",
    "llm_provider": "openai",
    "openai_api_key": "sk-test-...",
    "openclaw_model": "gpt-4"
  }'
```

#### Use Specific Config
```bash
curl -X POST .../containers \
  -H "Authorization: Bearer {USER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"config_name": "production"}'
```

### Update Configuration

#### Partial Update (Merge)
```bash
# Only update the model, keep everything else
curl -X PUT .../config/default \
  -H "Authorization: Bearer {USER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "openclaw_model": "claude-3-opus-20240229"
  }'
```

#### Full Replace (Overwrite)
```bash
# Replace entire config
curl -X PUT .../config/default?overwrite=true \
  -H "Authorization: Bearer {USER_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "llm_provider": "openai",
    "openai_api_key": "sk-new-key...",
    "openclaw_model": "gpt-4",
    "auth_gateway_api_key": "b13b7bb9cbe9ecfa112cf..."
  }'
```

## Configuration Merge Behavior

When a container is created, configs are merged as follows:

```python
# 1. Load system config (infrastructure)
system_config = {
    "auth_gateway_url": "https://your-auth-gateway...",
    "openclaw_url": "http://localhost:18789",
    "openclaw_token": "test-token-123"
}

# 2. Load user config (preferences + secrets)
user_config = {
    "llm_provider": "anthropic",
    "anthropic_api_key": "sk-ant-...",
    "openclaw_model": "claude-3-haiku-20240307",
    "auth_gateway_api_key": "b13b7bb9..."
}

# 3. Merge with user values taking precedence
final_config = {
    # From system config
    "auth_gateway_url": "https://your-auth-gateway...",
    "openclaw_url": "http://localhost:18789",
    "openclaw_token": "test-token-123",

    # From user config
    "llm_provider": "anthropic",
    "anthropic_api_key": "sk-ant-...",
    "openclaw_model": "claude-3-haiku-20240307",
    "auth_gateway_api_key": "b13b7bb9..."
}
```

**Key Principle:** User config values always override system config values for the same field.

## Security Considerations

- **API Keys in Transit:** All API calls should use HTTPS
- **API Keys at Rest:** Currently stored in plaintext in DynamoDB (encryption planned)
- **Access Control:** Users can only access their own configs; admins can access system config
- **Audit Trail:** All config updates include `created_at` and `updated_at` timestamps

## Future Parameters

The configuration system is designed to be extensible. Planned parameter additions include:

- Voice settings (voice type, speed, language)
- Agent behavior settings (response style, safety thresholds)
- Custom model configurations
- Webhook URLs for notifications
- Resource limits (max containers, timeout settings)
- Regional preferences

The API will continue to accept arbitrary JSON fields to support backward compatibility as new parameters are added.
