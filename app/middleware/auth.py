import hashlib
import logging
import secrets

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings
from app.services import dynamodb as db

logger = logging.getLogger(__name__)

# Global httpx client for auth-gateway requests (reused across requests)
_auth_client = None


def get_auth_client() -> httpx.AsyncClient:
    """Get or create the shared httpx client for auth-gateway requests."""
    global _auth_client
    if _auth_client is None:
        settings = get_settings()
        _auth_client = httpx.AsyncClient(timeout=settings.auth_gateway_timeout)
    return _auth_client


async def close_auth_client():
    """Close the shared httpx client."""
    global _auth_client
    if _auth_client is not None:
        await _auth_client.aclose()
        _auth_client = None


def _is_public(method: str, path: str) -> bool:
    if path in ("/health", "/", "/openapi.json"):
        return True
    if path.startswith(("/docs", "/redoc", "/static")):
        return True
    return False


class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Skip auth for public endpoints
        if _is_public(request.method, request.url.path):
            return await call_next(request)

        # Extract api_key from Authorization header
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse(
                {"detail": "Missing or invalid Authorization header"},
                status_code=401,
            )

        api_key = auth[len("Bearer ") :]
        settings = get_settings()

        # Check master API key (for admin operations)
        if settings.master_api_key and secrets.compare_digest(
            api_key, settings.master_api_key
        ):
            request.state.user_id = "master"
            request.state.api_key = api_key
            return await call_next(request)

        # Validate with auth-gateway
        try:
            client = get_auth_client()
            response = await client.get(
                f"{settings.auth_gateway_url}/auth",
                headers={"Authorization": f"Bearer {api_key}"},
            )

            if response.status_code != 200:
                logger.warning(
                    "auth rejected: status=%s path=%s",
                    response.status_code,
                    request.url.path,
                )
                return JSONResponse({"detail": "Invalid API key"}, status_code=401)

            # Extract user_id from auth-gateway response
            auth_data = response.json()
            user_id = auth_data.get("user_id")

            if not user_id:
                logger.error("auth-gateway returned 200 but no user_id: %s", auth_data)
                return JSONResponse(
                    {"detail": "Invalid auth response"}, status_code=500
                )

            logger.info("auth ok: user=%s path=%s", user_id, request.url.path)

            # Store in request state
            request.state.user_id = user_id
            request.state.api_key = api_key

        except httpx.TimeoutException:
            logger.error("auth-gateway timeout: path=%s", request.url.path)
            return JSONResponse({"detail": "Auth service timeout"}, status_code=503)
        except httpx.RequestError as e:
            logger.error("auth-gateway request error: %s path=%s", e, request.url.path)
            return JSONResponse(
                {"detail": f"Auth service error: {str(e)}"}, status_code=503
            )
        except Exception as e:
            logger.exception("unexpected auth error: path=%s", request.url.path)
            return JSONResponse({"detail": "Authentication failed"}, status_code=500)

        return await call_next(request)
