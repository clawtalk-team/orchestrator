"""
Configuration API endpoints.

Provides CRUD operations for user and system configurations stored in DynamoDB.
"""

import hmac
from typing import List

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.config import get_settings
from app.models.config import (
    SystemConfigResponse,
    SystemConfigUpdate,
    UserConfigCreate,
    UserConfigResponse,
    UserConfigUpdate,
)
from app.services.user_config import UserConfigService

router = APIRouter(prefix="/config", tags=["config"])


def _is_admin(request: Request) -> bool:
    """Check if the request is from an admin (master API key)."""
    settings = get_settings()
    if not settings.master_api_key:
        return False

    # Check if the API key matches the master key
    api_key = getattr(request.state, "api_key", None)
    if not api_key:
        return False

    # Constant-time comparison to prevent timing attacks
    return hmac.compare_digest(api_key, settings.master_api_key)


def _get_user_id(request: Request) -> str:
    """Extract user_id from request state (set by auth middleware)."""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    return user_id


@router.get(
    "",
    response_model=List[UserConfigResponse],
    response_model_exclude_none=True,
    summary="List user configurations",
    response_description="List of all user configurations"
)
async def list_user_configs(request: Request) -> List[UserConfigResponse]:
    """
    List all configurations for the authenticated user.

    Returns a list of all named configurations owned by the user.
    """
    user_id = _get_user_id(request)
    config_service = UserConfigService()

    # Query DynamoDB for all configs for this user
    from app.services.dynamodb import _get_table

    table = _get_table()
    response = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :sk_prefix)",
        ExpressionAttributeValues={
            ":pk": f"USER#{user_id}",
            ":sk_prefix": "CONFIG#"
        }
    )

    configs = []
    for item in response.get("Items", []):
        # Extract config_name from sk (format: CONFIG#{config_name})
        sk = item.get("sk", "")
        if not sk.startswith("CONFIG#"):
            continue

        config_name = sk[7:]  # Remove "CONFIG#" prefix
        # Process raw item directly to avoid N+1 query problem
        config_data = config_service._process_raw_item(item)

        # config_data includes created_at and updated_at from raw item
        configs.append({
            "config_name": config_name,
            "user_id": user_id,
            **config_data
        })

    return configs


@router.post(
    "",
    response_model=UserConfigResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
    summary="Create user configuration",
    response_description="Created configuration"
)
async def create_user_config(
    request: Request,
    config: UserConfigCreate
) -> UserConfigResponse:
    """
    Create a new user configuration.

    Creates a named configuration for the authenticated user. The config_name must
    be unique per user. Arbitrary JSON fields are supported beyond the standard fields.
    """
    user_id = _get_user_id(request)
    config_service = UserConfigService()

    # Check if config already exists
    existing = config_service.get_user_config(user_id, config.config_name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Configuration '{config.config_name}' already exists"
        )

    # Convert to dict and remove config_name (not stored in DynamoDB item)
    config_dict = config.model_dump(exclude={"config_name"}, exclude_none=True)

    # Save the config and get timestamps (avoids redundant database read)
    timestamps = config_service.save_user_config(
        user_id=user_id,
        config=config_dict,
        config_name=config.config_name,
        overwrite=False
    )

    # Construct response using saved data and returned timestamps
    response_data = {
        "config_name": config.config_name,
        "user_id": user_id,
        **config_dict,
        **timestamps
    }

    return UserConfigResponse(**response_data)


@router.get(
    "/system",
    response_model=SystemConfigResponse,
    summary="Get system configuration",
    response_description="System configuration",
    responses={403: {"description": "Admin access required"}}
)
async def get_system_config(request: Request) -> SystemConfigResponse:
    """
    Get system-wide configuration.

    Returns global system defaults. Requires admin access (master API key).
    """
    if not _is_admin(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )

    config_service = UserConfigService()
    system_config = config_service.get_system_config()

    # System config now includes updated_at, no redundant database read needed
    return SystemConfigResponse(**system_config)


@router.get(
    "/{config_name}",
    response_model=UserConfigResponse,
    response_model_exclude_none=True,
    summary="Get user configuration",
    response_description="Configuration details",
    responses={404: {"description": "Configuration not found"}}
)
async def get_user_config(
    request: Request,
    config_name: str,
    merged: bool = Query(
        True,
        description="If true, merge with system config (default); if false, return user config only"
    )
) -> UserConfigResponse:
    """
    Get a specific user configuration by name.

    Returns the configuration with the given name for the authenticated user.

    By default (merged=true), returns the merged configuration with system config values
    (auth_gateway_url, openclaw_url, openclaw_token, voice_gateway_url) included.
    This is required for containers to properly start openclaw-agent.

    Set merged=false to get only the user-specific configuration without system defaults.

    Returns 404 if the configuration does not exist.
    """
    user_id = _get_user_id(request)
    config_service = UserConfigService()

    # Check if user config exists
    user_config_data = config_service.get_user_config(user_id, config_name)
    if not user_config_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Configuration '{config_name}' not found"
        )

    if merged:
        # Return merged config with system values (required for containers)
        system_config = config_service.get_system_config()

        # Merge: user config overrides system config for shared fields
        config_data = {
            **system_config,
            **user_config_data
        }
    else:
        # Return only user config
        config_data = user_config_data

    # Add config_name for the response
    response_data = {
        "config_name": config_name,
        **config_data
    }

    return UserConfigResponse(**response_data)


@router.put(
    "/system",
    response_model=SystemConfigResponse,
    summary="Update system configuration",
    response_description="Updated system configuration",
    responses={403: {"description": "Admin access required"}}
)
async def update_system_config(
    request: Request,
    config: SystemConfigUpdate
) -> SystemConfigResponse:
    """
    Update system-wide configuration.

    Updates global system defaults. Requires admin access (master API key).
    """
    if not _is_admin(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )

    config_service = UserConfigService()

    # Convert to dict, excluding None values
    config_dict = config.model_dump(exclude_none=True)

    # Save system config
    config_service.save_system_config(config_dict)

    # Retrieve updated config (now includes updated_at, no redundant read)
    updated_config = config_service.get_system_config()

    return SystemConfigResponse(**updated_config)


@router.put(
    "/{config_name}",
    response_model=UserConfigResponse,
    response_model_exclude_none=True,
    summary="Update user configuration",
    response_description="Updated configuration"
)
async def update_user_config(
    request: Request,
    config_name: str,
    config: UserConfigUpdate,
    overwrite: bool = Query(
        False,
        description="If true, replace entire config; if false, merge with existing"
    )
) -> UserConfigResponse:
    """
    Update a user configuration.

    By default, merges with existing configuration (partial update).
    Use overwrite=true to replace the entire configuration.

    Creates a new configuration if it doesn't exist.
    """
    user_id = _get_user_id(request)
    config_service = UserConfigService()

    # Convert to dict, excluding None values
    config_dict = config.model_dump(exclude_none=True)

    # Get existing config for merge case
    existing_config = config_service.get_user_config(user_id, config_name) if not overwrite else None

    # Save the config (will merge or overwrite based on parameter)
    timestamps = config_service.save_user_config(
        user_id=user_id,
        config=config_dict,
        config_name=config_name,
        overwrite=overwrite
    )

    # Construct response based on operation type
    if overwrite:
        # For overwrite, response is just the new config + timestamps
        response_data = {
            "config_name": config_name,
            "user_id": user_id,
            **config_dict,
            **timestamps
        }
    else:
        # For merge, combine existing (if any) + new config + timestamps
        merged_config = {**(existing_config or {}), **config_dict}
        response_data = {
            "config_name": config_name,
            "user_id": user_id,
            **merged_config,
            **timestamps
        }

    return UserConfigResponse(**response_data)


@router.delete(
    "/{config_name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete user configuration",
    responses={404: {"description": "Configuration not found"}}
)
async def delete_user_config(
    request: Request,
    config_name: str
) -> None:
    """
    Delete a user configuration.

    Permanently deletes the configuration with the given name for the authenticated user.
    Returns 404 if the configuration does not exist.
    """
    user_id = _get_user_id(request)
    config_service = UserConfigService()

    # Check if config exists
    existing = config_service.get_user_config(user_id, config_name)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Configuration '{config_name}' not found"
        )

    # Delete from DynamoDB
    from app.services.dynamodb import _get_table

    table = _get_table()
    table.delete_item(
        Key={"pk": f"USER#{user_id}", "sk": f"CONFIG#{config_name}"}
    )
