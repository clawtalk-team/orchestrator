import hashlib
import secrets
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.services import dynamodb as db
from app.config import get_settings


def _is_public(method: str, path: str) -> bool:
    if path in ("/health", "/", "/openapi.json"):
        return True
    if path.startswith(("/docs", "/redoc", "/static")):
        return True
    return False


class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if _is_public(request.method, request.url.path):
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse(
                {"detail": "Missing or invalid Authorization header"},
                status_code=401,
            )

        key = auth[len("Bearer "):]
        settings = get_settings()

        # Check master API key first
        if settings.master_api_key and secrets.compare_digest(key, settings.master_api_key):
            request.state.user_id = "master"
            return await call_next(request)

        # In Phase 1, validate token format; auth-gateway validation deferred to Phase 2
        if not key or len(key) < 20:
            return JSONResponse({"detail": "Invalid API key"}, status_code=401)

        # Extract user_id from token (format: user_uuid:token_hash)
        try:
            user_id, _ = key.split(":", 1)
            request.state.user_id = user_id
        except ValueError:
            return JSONResponse({"detail": "Invalid API key format"}, status_code=401)

        return await call_next(request)
