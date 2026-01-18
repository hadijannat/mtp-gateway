"""FastAPI dependencies for WebUI.

Provides dependency injection for:
- TagManager and ServiceManager access
- JWT authentication
- Permission checking
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from mtp_gateway.adapters.northbound.webui.security.jwt import TokenPayload, TokenService
from mtp_gateway.adapters.northbound.webui.security.rbac import Permission, User

if TYPE_CHECKING:
    from mtp_gateway.application.service_manager import ServiceManager
    from mtp_gateway.application.tag_manager import TagManager
    from mtp_gateway.config.schema import GatewayConfig

logger = structlog.get_logger(__name__)

# HTTP Bearer token security scheme
oauth2_scheme = HTTPBearer(auto_error=False)


def get_tag_manager(request: Request) -> "TagManager":
    """Get TagManager from app state.

    Args:
        request: FastAPI request

    Returns:
        TagManager instance
    """
    return request.app.state.tag_manager


def get_service_manager(request: Request) -> "ServiceManager | None":
    """Get ServiceManager from app state.

    Args:
        request: FastAPI request

    Returns:
        ServiceManager instance or None
    """
    return request.app.state.service_manager


def get_token_service(request: Request) -> TokenService:
    """Get TokenService from app state.

    Args:
        request: FastAPI request

    Returns:
        TokenService instance
    """
    return request.app.state.token_service


def get_config(request: Request) -> "GatewayConfig":
    """Get GatewayConfig from app state.

    Args:
        request: FastAPI request

    Returns:
        GatewayConfig instance
    """
    return request.app.state.config


async def get_current_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(oauth2_scheme)],
    token_service: Annotated[TokenService, Depends(get_token_service)],
) -> TokenPayload:
    """Validate JWT token and return payload.

    Args:
        credentials: HTTP Bearer credentials
        token_service: JWT token service

    Returns:
        Decoded token payload

    Raises:
        HTTPException: If token is missing or invalid
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = token_service.decode_token(credentials.credentials)

        # Verify it's an access token
        if payload.type != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return payload

    except JWTError as e:
        logger.debug("Token validation failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


async def get_current_user(
    token: Annotated[TokenPayload, Depends(get_current_token)],
) -> User:
    """Get current user from token.

    Args:
        token: Validated token payload

    Returns:
        User model with permissions
    """
    # Create user from token payload
    # In a real app, you'd fetch from database
    return User(
        id=0,  # Would come from database
        username=token.sub,
        email="",  # Would come from database
        role="",  # Would come from database
        permissions=token.permissions,
        is_active=True,
    )


def require_permission(permission: str | Permission):
    """Create a dependency that requires a specific permission.

    Usage:
        @router.get("/admin", dependencies=[Depends(require_permission("admin:write"))])
        async def admin_endpoint():
            ...

    Args:
        permission: Required permission string or Permission enum

    Returns:
        Dependency function
    """
    perm_str = permission.value if isinstance(permission, Permission) else permission

    async def check_permission(
        user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        if perm_str not in user.permissions:
            logger.warning(
                "Permission denied",
                username=user.username,
                required=perm_str,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: requires {perm_str}",
            )
        return user

    return check_permission


# Type aliases for cleaner route signatures
TagManagerDep = Annotated["TagManager", Depends(get_tag_manager)]
ServiceManagerDep = Annotated["ServiceManager | None", Depends(get_service_manager)]
TokenServiceDep = Annotated[TokenService, Depends(get_token_service)]
ConfigDep = Annotated["GatewayConfig", Depends(get_config)]
CurrentUserDep = Annotated[User, Depends(get_current_user)]
