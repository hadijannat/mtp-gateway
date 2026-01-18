"""Security module for WebUI.

Provides:
- JWT token creation and validation
- Password hashing with Argon2id
- Role-based access control (RBAC)
"""

from mtp_gateway.adapters.northbound.webui.security.jwt import (
    TokenPayload,
    TokenService,
)
from mtp_gateway.adapters.northbound.webui.security.password import (
    PasswordService,
    hash_password,
    verify_password,
)
from mtp_gateway.adapters.northbound.webui.security.rbac import (
    Permission,
    RBACService,
    Role,
    User,
    get_permissions_for_role,
)

__all__ = [
    "PasswordService",
    "Permission",
    "RBACService",
    "Role",
    "TokenPayload",
    "TokenService",
    "User",
    "get_permissions_for_role",
    "hash_password",
    "verify_password",
]
