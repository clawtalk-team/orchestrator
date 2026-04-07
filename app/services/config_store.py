"""SSM Parameter Store service for config storage."""
import json
from typing import Any, Dict, Optional

import boto3

from app.config import get_settings


def _get_ssm_client():
    settings = get_settings()
    return boto3.client("ssm", region_name=settings.dynamodb_region)


def store_config(user_id: str, container_id: str, config: Dict[str, Any]) -> str:
    """
    Store container configuration in SSM Parameter Store.

    Returns the parameter path.
    """
    settings = get_settings()
    ssm = _get_ssm_client()

    param_name = f"{settings.ssm_prefix}/{user_id}/{container_id}"
    config_json = json.dumps(config)

    ssm.put_parameter(
        Name=param_name,
        Value=config_json,
        Type="SecureString",
        Overwrite=True,
        Description=f"Config for container {container_id} (user {user_id})",
    )

    return param_name


def get_config(user_id: str, container_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve container configuration from SSM."""
    settings = get_settings()
    ssm = _get_ssm_client()

    param_name = f"{settings.ssm_prefix}/{user_id}/{container_id}"

    try:
        response = ssm.get_parameter(Name=param_name, WithDecryption=True)
        return json.loads(response["Parameter"]["Value"])
    except ssm.exceptions.ParameterNotFound:
        return None


def delete_config(user_id: str, container_id: str) -> bool:
    """Delete container configuration from SSM."""
    settings = get_settings()
    ssm = _get_ssm_client()

    param_name = f"{settings.ssm_prefix}/{user_id}/{container_id}"

    try:
        ssm.delete_parameter(Name=param_name)
        return True
    except ssm.exceptions.ParameterNotFound:
        return False
