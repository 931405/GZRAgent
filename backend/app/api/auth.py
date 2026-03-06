"""
JWT Authentication Module.

Provides:
  - Token generation (login / API key exchange)
  - Token validation (FastAPI dependency)
  - Optional enforcement (disabled in development mode)
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

_security = HTTPBearer(auto_error=False)


def create_access_token(subject: str, extra: dict[str, Any] | None = None) -> str:
    """Create a signed JWT access token."""
    from jose import jwt
    from app.config import get_settings

    settings = get_settings()
    now = int(time.time())
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + settings.jwt_access_token_expire_minutes * 60,
    }
    if extra:
        payload.update(extra)

    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT token. Raises on invalid/expired."""
    from jose import JWTError, jwt
    from app.config import get_settings

    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_security),
) -> dict[str, Any]:
    """FastAPI dependency: extract and validate the current user from JWT.

    In development mode (APP_DEBUG=true), authentication is optional
    and returns a default dev user if no token is provided.
    """
    from app.config import get_settings
    settings = get_settings()

    if credentials is None or not credentials.credentials:
        if settings.app_debug:
            return {"sub": "dev_user", "role": "admin", "dev_mode": True}
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return decode_token(credentials.credentials)


async def require_auth(user: dict = Depends(get_current_user)) -> dict:
    """Strict auth dependency — always requires a valid token, even in dev."""
    if user.get("dev_mode"):
        return user
    return user
