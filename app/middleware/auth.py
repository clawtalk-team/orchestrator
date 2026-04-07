import hashlib
import secrets

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings
from app.services import dynamodb as db


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
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{settings.auth_gateway_url}/auth",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=5.0,
                )

            if response.status_code != 200:
                return JSONResponse({"detail": "Invalid API key"}, status_code=401)

            # Extract user_id from auth-gateway response
            auth_data = response.json()
            user_id = auth_data.get("user_id")

            if not user_id:
                return JSONResponse(
                    {"detail": "Invalid auth response"}, status_code=500
                )

            # Store in request state
            request.state.user_id = user_id
            request.state.api_key = api_key

        except httpx.TimeoutException:
            return JSONResponse({"detail": "Auth service timeout"}, status_code=503)
        except httpx.RequestError as e:
            return JSONResponse(
                {"detail": f"Auth service error: {str(e)}"}, status_code=503
            )
        except Exception as e:
            return JSONResponse({"detail": "Authentication failed"}, status_code=500)

        return await call_next(request)
