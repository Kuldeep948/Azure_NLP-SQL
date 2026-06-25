"""Authentication middleware for the NLP-to-SQL Azure Harness API.

Provides bearer token validation as a FastAPI dependency. Supports:
- Local development: validates against a static token or accepts all tokens
- Production: Azure AD JWT validation (JWKS-based, stubbed for full implementation)

Requirements: 8.1, 8.2, 8.3
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)

# Environment variable for local dev static token (optional)
_LOCAL_DEV_TOKEN_ENV = "AUTH_DEV_TOKEN"


def _is_local_environment() -> bool:
    """Detect local development by absence of Azure Managed Identity endpoint."""
    return os.environ.get("IDENTITY_ENDPOINT") is None


async def authenticate(request: Request) -> dict[str, Any]:
    """FastAPI dependency that validates bearer tokens and returns user info.

    Extracts the bearer token from the Authorization header and validates it.

    For local development:
        - If AUTH_DEV_TOKEN is set, validates the token against it.
        - If AUTH_DEV_TOKEN is not set, accepts any bearer token (dev convenience).

    For production:
        - Validates JWT against Azure AD JWKS endpoint.
        - Verifies issuer, audience, and expiration claims.

    Args:
        request: The incoming FastAPI Request.

    Returns:
        A user info dict with:
            - user_id: str — the authenticated user's identity
            - roles: list[str] — the user's role claims

    Raises:
        HTTPException(401): If the token is missing, invalid, or expired.
    """
    # Extract Authorization header
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Validate bearer scheme
    parts = auth_header.split(" ", maxsplit=1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format. Expected: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = parts[1].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Empty bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Route to appropriate validation strategy
    if _is_local_environment():
        return _validate_local(token)
    else:
        return await _validate_azure_ad(token, request)


def _validate_local(token: str) -> dict[str, Any]:
    """Validate token for local development.

    If AUTH_DEV_TOKEN is configured, the provided token must match.
    If AUTH_DEV_TOKEN is not configured, any non-empty token is accepted
    for development convenience.

    Returns:
        User info dict with user_id and roles.
    """
    dev_token = os.environ.get(_LOCAL_DEV_TOKEN_ENV)

    if dev_token and token != dev_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # In local dev, return a default user identity
    return {
        "user_id": "local-dev-user",
        "roles": ["admin", "analyst"],
    }


async def _validate_azure_ad(token: str, request: Request) -> dict[str, Any]:
    """Validate JWT token against Azure AD.

    NOTE: Full JWKS validation is stubbed here. In production, this should:
    1. Fetch JWKS from Azure AD discovery endpoint
    2. Decode and verify the JWT signature using the appropriate key
    3. Validate issuer (iss), audience (aud), and expiration (exp) claims
    4. Extract user_id from 'oid' or 'sub' claim
    5. Extract roles from 'roles' claim array

    TODO: Implement full JWKS validation with python-jose or PyJWT + cryptography.
    Consider caching the JWKS keys with a TTL of ~24 hours.

    For now, performs basic JWT structure validation and claim extraction
    without signature verification.
    """
    import base64
    import json
    from datetime import datetime, timezone

    try:
        # Split JWT into parts
        jwt_parts = token.split(".")
        if len(jwt_parts) != 3:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token format",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Decode payload (middle part)
        payload_b64 = jwt_parts[1]
        # Add padding if necessary
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding

        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        claims = json.loads(payload_bytes)

        # Validate expiration
        exp = claims.get("exp")
        if exp is not None:
            exp_dt = datetime.fromtimestamp(exp, tz=timezone.utc)
            if exp_dt < datetime.now(tz=timezone.utc):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token has expired",
                    headers={"WWW-Authenticate": "Bearer"},
                )

        # Validate issuer (if configured)
        expected_issuer = os.environ.get("AUTH_ISSUER")
        if expected_issuer:
            token_issuer = claims.get("iss", "")
            if token_issuer != expected_issuer:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token issuer",
                    headers={"WWW-Authenticate": "Bearer"},
                )

        # Validate audience (if configured)
        expected_audience = os.environ.get("AUTH_AUDIENCE")
        if expected_audience:
            token_audience = claims.get("aud", "")
            if token_audience != expected_audience:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token audience",
                    headers={"WWW-Authenticate": "Bearer"},
                )

        # Extract user identity
        user_id = claims.get("oid") or claims.get("sub") or claims.get("unique_name", "unknown")
        roles = claims.get("roles", [])

        # If no roles claim, check for wids (directory roles) or assign default
        if not roles:
            roles = ["user"]

        return {
            "user_id": str(user_id),
            "roles": roles,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Token validation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or malformed token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
