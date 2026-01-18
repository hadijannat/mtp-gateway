"""Role-Based Access Control (RBAC) for WebUI.

Defines permissions and roles for controlling access to WebUI features.
Follows the principle of least privilege - users only get the permissions
they need for their role.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

import structlog
from pydantic import BaseModel

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = structlog.get_logger(__name__)


class Permission(str, Enum):
    """Available permissions in the WebUI system.

    Permissions follow the pattern: resource:action
    """

    # Tag permissions
    TAGS_READ = "tags:read"
    TAGS_WRITE = "tags:write"

    # Service permissions
    SERVICES_READ = "services:read"
    SERVICES_COMMAND = "services:command"

    # Alarm permissions
    ALARMS_READ = "alarms:read"
    ALARMS_ACK = "alarms:ack"
    ALARMS_SHELVE = "alarms:shelve"

    # History permissions
    HISTORY_READ = "history:read"

    # Config permissions
    CONFIG_READ = "config:read"
    CONFIG_WRITE = "config:write"

    # User management permissions
    USERS_READ = "users:read"
    USERS_WRITE = "users:write"


class Role(str, Enum):
    """Predefined roles with associated permissions.

    Role hierarchy:
    - operator: Basic operational access
    - engineer: Extended access for configuration and troubleshooting
    - admin: Full system access
    """

    OPERATOR = "operator"
    ENGINEER = "engineer"
    ADMIN = "admin"


# Role to permissions mapping
ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.OPERATOR: {
        Permission.TAGS_READ,
        Permission.SERVICES_READ,
        Permission.SERVICES_COMMAND,
        Permission.ALARMS_READ,
        Permission.ALARMS_ACK,
        Permission.HISTORY_READ,
    },
    Role.ENGINEER: {
        Permission.TAGS_READ,
        Permission.TAGS_WRITE,
        Permission.SERVICES_READ,
        Permission.SERVICES_COMMAND,
        Permission.ALARMS_READ,
        Permission.ALARMS_ACK,
        Permission.ALARMS_SHELVE,
        Permission.HISTORY_READ,
        Permission.CONFIG_READ,
    },
    Role.ADMIN: {
        Permission.TAGS_READ,
        Permission.TAGS_WRITE,
        Permission.SERVICES_READ,
        Permission.SERVICES_COMMAND,
        Permission.ALARMS_READ,
        Permission.ALARMS_ACK,
        Permission.ALARMS_SHELVE,
        Permission.HISTORY_READ,
        Permission.CONFIG_READ,
        Permission.CONFIG_WRITE,
        Permission.USERS_READ,
        Permission.USERS_WRITE,
    },
}


class User(BaseModel):
    """User model with role and permissions.

    Attributes:
        id: Database user ID
        username: Unique username
        email: User email address
        role: User's role
        permissions: Explicit permission list (cached from role)
        is_active: Whether user account is active
    """

    id: int
    username: str
    email: str
    role: str
    permissions: list[str]
    is_active: bool = True


class RBACService:
    """Service for role-based access control checks.

    Provides methods to check if a user has specific permissions
    and to resolve role permissions.
    """

    def __init__(
        self,
        role_permissions: dict[str, set[str]] | None = None,
    ) -> None:
        """Initialize RBAC service.

        Args:
            role_permissions: Custom role to permissions mapping.
                            If None, uses default ROLE_PERMISSIONS.
        """
        if role_permissions is not None:
            self._role_permissions = role_permissions
        else:
            # Convert enum-based mapping to string-based for flexibility
            self._role_permissions = {
                role.value: {p.value for p in perms} for role, perms in ROLE_PERMISSIONS.items()
            }

    def get_role_permissions(self, role: str) -> set[str]:
        """Get all permissions for a role.

        Args:
            role: Role name

        Returns:
            Set of permission strings for the role
        """
        return self._role_permissions.get(role, set())

    def has_permission(
        self,
        user_permissions: Iterable[str],
        required_permission: str | Permission,
    ) -> bool:
        """Check if user has a specific permission.

        Args:
            user_permissions: List of permissions the user has
            required_permission: Permission to check for

        Returns:
            True if user has the permission
        """
        if isinstance(required_permission, Permission):
            required_permission = required_permission.value

        permission_set = set(user_permissions)
        has_perm = required_permission in permission_set

        logger.debug(
            "Permission check",
            required=required_permission,
            granted=has_perm,
        )

        return has_perm

    def has_any_permission(
        self,
        user_permissions: Iterable[str],
        required_permissions: Iterable[str | Permission],
    ) -> bool:
        """Check if user has any of the specified permissions.

        Args:
            user_permissions: List of permissions the user has
            required_permissions: Permissions to check for (any)

        Returns:
            True if user has at least one of the permissions
        """
        permission_set = set(user_permissions)
        required_set = {p.value if isinstance(p, Permission) else p for p in required_permissions}

        has_any = bool(permission_set & required_set)

        logger.debug(
            "Any permission check",
            required=list(required_set),
            granted=has_any,
        )

        return has_any

    def has_all_permissions(
        self,
        user_permissions: Iterable[str],
        required_permissions: Iterable[str | Permission],
    ) -> bool:
        """Check if user has all of the specified permissions.

        Args:
            user_permissions: List of permissions the user has
            required_permissions: Permissions to check for (all)

        Returns:
            True if user has all of the permissions
        """
        permission_set = set(user_permissions)
        required_set = {p.value if isinstance(p, Permission) else p for p in required_permissions}

        has_all = required_set <= permission_set

        logger.debug(
            "All permissions check",
            required=list(required_set),
            granted=has_all,
        )

        return has_all

    def check_user_permission(
        self,
        user: User,
        required_permission: str | Permission,
    ) -> bool:
        """Check if a user has a specific permission.

        Also checks if the user account is active.

        Args:
            user: User to check
            required_permission: Permission required

        Returns:
            True if user is active and has the permission
        """
        if not user.is_active:
            logger.debug(
                "Permission denied - user inactive",
                username=user.username,
            )
            return False

        return self.has_permission(user.permissions, required_permission)


def require_permission(permission: str | Permission) -> str:
    """Get permission string for use in route dependencies.

    Args:
        permission: Permission to require

    Returns:
        Permission string value
    """
    if isinstance(permission, Permission):
        return permission.value
    return permission


def get_permissions_for_role(role: str) -> list[str]:
    """Get list of permission strings for a role.

    Args:
        role: Role name

    Returns:
        List of permission strings
    """
    try:
        role_enum = Role(role)
        return [p.value for p in ROLE_PERMISSIONS[role_enum]]
    except (ValueError, KeyError):
        logger.warning("Unknown role requested", role=role)
        return []


# Default RBAC service instance
_default_service: RBACService | None = None


def get_rbac_service() -> RBACService:
    """Get or create the default RBAC service.

    Returns:
        Shared RBACService instance
    """
    global _default_service  # noqa: PLW0603
    if _default_service is None:
        _default_service = RBACService()
    return _default_service
