"""Authentication router.

Provides endpoints for login, token refresh, and user info.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, status
from jose import JWTError

from mtp_gateway.adapters.northbound.webui.dependencies import (  # noqa: TC001
    CurrentUserDep,
    TokenServiceDep,
)
from mtp_gateway.adapters.northbound.webui.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    TokenResponse,
    UserResponse,
)
from mtp_gateway.adapters.northbound.webui.security.password import verify_password
from mtp_gateway.adapters.northbound.webui.security.rbac import get_permissions_for_role

logger = structlog.get_logger(__name__)

router = APIRouter()

# Mock user database - replace with real database in production
_MOCK_USERS = {
    "admin": {
        "id": 1,
        "username": "admin",
        "email": "admin@localhost",
        "password_hash": (
            "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$RdescudvJCsgt3ub+b+dWRWJTmaaJObG"
        ),
        "role": "admin",
        "is_active": True,
    },
    "operator": {
        "id": 2,
        "username": "operator",
        "email": "operator@localhost",
        "password_hash": (
            "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$RdescudvJCsgt3ub+b+dWRWJTmaaJObG"
        ),
        "role": "operator",
        "is_active": True,
    },
}


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    token_service: TokenServiceDep,
) -> LoginResponse:
    """Authenticate user and return tokens.

    Args:
        request: Login credentials
        token_service: JWT token service

    Returns:
        Access and refresh tokens with user info

    Raises:
        HTTPException: If credentials are invalid
    """
    # Look up user
    user_data = _MOCK_USERS.get(request.username)
    if not user_data:
        logger.warning("Login failed - user not found", username=request.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    # Verify password
    if not verify_password(request.password, user_data["password_hash"]):
        logger.warning("Login failed - invalid password", username=request.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    # Check if user is active
    if not user_data["is_active"]:
        logger.warning("Login failed - account disabled", username=request.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is disabled",
        )

    # Get permissions for role
    permissions = get_permissions_for_role(user_data["role"])

    # Create tokens
    access_token, refresh_token = token_service.create_token_pair(
        username=user_data["username"],
        permissions=permissions,
    )

    logger.info("User logged in", username=request.username, role=user_data["role"])

    return LoginResponse(
        tokens=TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=token_service._access_expiry_minutes * 60,
        ),
        user=UserResponse(
            id=user_data["id"],
            username=user_data["username"],
            email=user_data["email"],
            role=user_data["role"],
            permissions=permissions,
            is_active=user_data["is_active"],
        ),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    request: RefreshRequest,
    token_service: TokenServiceDep,
) -> TokenResponse:
    """Refresh access token using refresh token.

    Args:
        request: Refresh token
        token_service: JWT token service

    Returns:
        New access and refresh tokens

    Raises:
        HTTPException: If refresh token is invalid
    """
    try:
        # Decode refresh token
        payload = token_service.decode_token(request.refresh_token)

        # Verify it's a refresh token
        if payload.type != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
            )

        # Look up user to get current permissions
        user_data = _MOCK_USERS.get(payload.sub)
        if not user_data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
            )

        if not user_data["is_active"]:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Account is disabled",
            )

        # Get current permissions
        permissions = get_permissions_for_role(user_data["role"])

        # Create new token pair
        access_token, refresh_token = token_service.create_token_pair(
            username=payload.sub,
            permissions=permissions,
        )

        logger.debug("Token refreshed", username=payload.sub)

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=token_service._access_expiry_minutes * 60,
        )

    except JWTError as e:
        logger.warning("Token refresh failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        ) from e


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: CurrentUserDep,
) -> UserResponse:
    """Get current authenticated user info.

    Args:
        current_user: Current authenticated user

    Returns:
        User information
    """
    # In a real app, fetch fresh data from database
    user_data = _MOCK_USERS.get(current_user.username)
    if not user_data:
        return UserResponse(
            id=0,
            username=current_user.username,
            email="",
            role="",
            permissions=current_user.permissions,
            is_active=True,
        )

    return UserResponse(
        id=user_data["id"],
        username=user_data["username"],
        email=user_data["email"],
        role=user_data["role"],
        permissions=current_user.permissions,
        is_active=user_data["is_active"],
    )
