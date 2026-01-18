"""Tests for WebUI Role-Based Access Control.

Tests for:
- Permission checking
- Role permission mapping
- User authorization
"""

from __future__ import annotations

import pytest

from mtp_gateway.adapters.northbound.webui.security.rbac import (
    Permission,
    RBACService,
    Role,
    User,
    get_permissions_for_role,
    get_rbac_service,
)


class TestPermission:
    """Tests for Permission enum."""

    def test_permission_values(self) -> None:
        """Permissions should have correct string values."""
        assert Permission.TAGS_READ.value == "tags:read"
        assert Permission.SERVICES_COMMAND.value == "services:command"
        assert Permission.ALARMS_ACK.value == "alarms:ack"

    def test_all_permissions_follow_pattern(self) -> None:
        """All permissions should follow resource:action pattern."""
        for perm in Permission:
            assert ":" in perm.value
            resource, action = perm.value.split(":")
            assert len(resource) > 0
            assert len(action) > 0


class TestRole:
    """Tests for Role enum."""

    def test_role_values(self) -> None:
        """Roles should have correct string values."""
        assert Role.OPERATOR.value == "operator"
        assert Role.ENGINEER.value == "engineer"
        assert Role.ADMIN.value == "admin"


class TestRBACService:
    """Tests for RBACService."""

    @pytest.fixture
    def rbac_service(self) -> RBACService:
        """Create an RBACService instance for testing."""
        return RBACService()

    def test_get_role_permissions_operator(self, rbac_service: RBACService) -> None:
        """Operator should have basic operational permissions."""
        perms = rbac_service.get_role_permissions("operator")

        assert "tags:read" in perms
        assert "services:read" in perms
        assert "services:command" in perms
        assert "alarms:read" in perms
        assert "alarms:ack" in perms

        # Should NOT have elevated permissions
        assert "tags:write" not in perms
        assert "config:write" not in perms
        assert "users:write" not in perms

    def test_get_role_permissions_engineer(self, rbac_service: RBACService) -> None:
        """Engineer should have extended permissions."""
        perms = rbac_service.get_role_permissions("engineer")

        # All operator permissions
        assert "tags:read" in perms
        assert "services:command" in perms
        assert "alarms:ack" in perms

        # Plus engineer-specific
        assert "tags:write" in perms
        assert "alarms:shelve" in perms
        assert "config:read" in perms

        # But not admin permissions
        assert "config:write" not in perms
        assert "users:write" not in perms

    def test_get_role_permissions_admin(self, rbac_service: RBACService) -> None:
        """Admin should have all permissions."""
        perms = rbac_service.get_role_permissions("admin")

        assert "tags:read" in perms
        assert "tags:write" in perms
        assert "services:command" in perms
        assert "config:read" in perms
        assert "config:write" in perms
        assert "users:read" in perms
        assert "users:write" in perms

    def test_get_role_permissions_unknown_role(self, rbac_service: RBACService) -> None:
        """Unknown role should return empty set."""
        perms = rbac_service.get_role_permissions("unknown_role")

        assert perms == set()

    def test_has_permission_with_string(self, rbac_service: RBACService) -> None:
        """Should check permission with string value."""
        user_perms = ["tags:read", "services:read"]

        assert rbac_service.has_permission(user_perms, "tags:read") is True
        assert rbac_service.has_permission(user_perms, "tags:write") is False

    def test_has_permission_with_enum(self, rbac_service: RBACService) -> None:
        """Should check permission with Permission enum."""
        user_perms = ["tags:read", "services:read"]

        assert rbac_service.has_permission(user_perms, Permission.TAGS_READ) is True
        assert rbac_service.has_permission(user_perms, Permission.TAGS_WRITE) is False

    def test_has_any_permission(self, rbac_service: RBACService) -> None:
        """Should return True if user has any of the required permissions."""
        user_perms = ["tags:read", "alarms:read"]

        # Has one of them
        assert rbac_service.has_any_permission(user_perms, ["tags:read", "tags:write"]) is True

        # Has none of them
        assert rbac_service.has_any_permission(user_perms, ["config:read", "config:write"]) is False

    def test_has_any_permission_with_enum(self, rbac_service: RBACService) -> None:
        """Should work with Permission enum."""
        user_perms = ["tags:read"]

        assert (
            rbac_service.has_any_permission(
                user_perms, [Permission.TAGS_READ, Permission.TAGS_WRITE]
            )
            is True
        )

    def test_has_all_permissions(self, rbac_service: RBACService) -> None:
        """Should return True only if user has all required permissions."""
        user_perms = ["tags:read", "tags:write", "alarms:read"]

        # Has all of them
        assert rbac_service.has_all_permissions(user_perms, ["tags:read", "tags:write"]) is True

        # Missing one
        assert (
            rbac_service.has_all_permissions(user_perms, ["tags:read", "config:read"]) is False
        )

    def test_has_all_permissions_with_enum(self, rbac_service: RBACService) -> None:
        """Should work with Permission enum."""
        user_perms = ["tags:read", "tags:write"]

        assert (
            rbac_service.has_all_permissions(
                user_perms, [Permission.TAGS_READ, Permission.TAGS_WRITE]
            )
            is True
        )


class TestUserPermissionChecks:
    """Tests for user-level permission checks."""

    @pytest.fixture
    def rbac_service(self) -> RBACService:
        """Create an RBACService instance for testing."""
        return RBACService()

    @pytest.fixture
    def active_user(self) -> User:
        """Create an active user for testing."""
        return User(
            id=1,
            username="testuser",
            email="test@example.com",
            role="operator",
            permissions=["tags:read", "services:read", "services:command"],
            is_active=True,
        )

    @pytest.fixture
    def inactive_user(self) -> User:
        """Create an inactive user for testing."""
        return User(
            id=2,
            username="inactive",
            email="inactive@example.com",
            role="operator",
            permissions=["tags:read"],
            is_active=False,
        )

    def test_check_user_permission_active_user_has_perm(
        self, rbac_service: RBACService, active_user: User
    ) -> None:
        """Active user with permission should be allowed."""
        assert rbac_service.check_user_permission(active_user, "tags:read") is True

    def test_check_user_permission_active_user_no_perm(
        self, rbac_service: RBACService, active_user: User
    ) -> None:
        """Active user without permission should be denied."""
        assert rbac_service.check_user_permission(active_user, "tags:write") is False

    def test_check_user_permission_inactive_user(
        self, rbac_service: RBACService, inactive_user: User
    ) -> None:
        """Inactive user should always be denied."""
        assert rbac_service.check_user_permission(inactive_user, "tags:read") is False


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_get_permissions_for_role_operator(self) -> None:
        """Should return operator permissions."""
        perms = get_permissions_for_role("operator")

        assert "tags:read" in perms
        assert "services:command" in perms
        assert isinstance(perms, list)

    def test_get_permissions_for_role_admin(self) -> None:
        """Should return admin permissions."""
        perms = get_permissions_for_role("admin")

        assert "users:write" in perms
        assert "config:write" in perms

    def test_get_permissions_for_role_unknown(self) -> None:
        """Unknown role should return empty list."""
        perms = get_permissions_for_role("unknown")

        assert perms == []

    def test_get_rbac_service_singleton(self) -> None:
        """Should return the same instance."""
        service1 = get_rbac_service()
        service2 = get_rbac_service()

        assert service1 is service2


class TestCustomRolePermissions:
    """Tests for custom role permission configuration."""

    def test_custom_role_permissions(self) -> None:
        """Should use custom role permissions when provided."""
        custom_perms = {
            "viewer": {"tags:read"},
            "editor": {"tags:read", "tags:write"},
        }

        service = RBACService(role_permissions=custom_perms)

        assert service.get_role_permissions("viewer") == {"tags:read"}
        assert service.get_role_permissions("editor") == {"tags:read", "tags:write"}
        assert service.get_role_permissions("operator") == set()  # Default not available
