"""Tests for WebUI password hashing.

Tests for:
- Password hashing with Argon2id
- Password verification
- Rehash detection
- Error handling
"""

from __future__ import annotations

import pytest

from mtp_gateway.adapters.northbound.webui.security.password import (
    PasswordService,
    get_password_service,
    hash_password,
    verify_password,
)


class TestPasswordService:
    """Tests for PasswordService."""

    @pytest.fixture
    def password_service(self) -> PasswordService:
        """Create a PasswordService instance for testing."""
        # Use lower cost for faster tests
        return PasswordService(
            time_cost=1,
            memory_cost=1024,  # 1 MiB for fast tests
            parallelism=1,
        )

    def test_hash_password_returns_string(self, password_service: PasswordService) -> None:
        """Should return an Argon2id hash string."""
        hash_value = password_service.hash_password("testpassword")

        assert isinstance(hash_value, str)
        assert hash_value.startswith("$argon2id$")

    def test_hash_password_contains_parameters(self, password_service: PasswordService) -> None:
        """Hash should contain embedded parameters."""
        hash_value = password_service.hash_password("testpassword")

        # Argon2id format: $argon2id$v=19$m=memory,t=time,p=parallel$salt$hash
        assert "$v=19$" in hash_value
        assert "$m=" in hash_value
        assert ",t=" in hash_value
        assert ",p=" in hash_value

    def test_hash_password_produces_unique_hashes(self, password_service: PasswordService) -> None:
        """Same password should produce different hashes (random salt)."""
        hash1 = password_service.hash_password("testpassword")
        hash2 = password_service.hash_password("testpassword")

        assert hash1 != hash2

    def test_hash_password_rejects_empty_password(self, password_service: PasswordService) -> None:
        """Should reject empty passwords."""
        with pytest.raises(ValueError, match="cannot be empty"):
            password_service.hash_password("")

    def test_verify_password_returns_true_for_valid(
        self, password_service: PasswordService
    ) -> None:
        """Should return True for correct password."""
        password = "correctpassword"
        hash_value = password_service.hash_password(password)

        assert password_service.verify_password(password, hash_value) is True

    def test_verify_password_returns_false_for_invalid(
        self, password_service: PasswordService
    ) -> None:
        """Should return False for incorrect password."""
        hash_value = password_service.hash_password("correctpassword")

        assert password_service.verify_password("wrongpassword", hash_value) is False

    def test_verify_password_returns_false_for_empty_password(
        self, password_service: PasswordService
    ) -> None:
        """Should return False for empty password."""
        hash_value = password_service.hash_password("somepassword")

        assert password_service.verify_password("", hash_value) is False

    def test_verify_password_returns_false_for_empty_hash(
        self, password_service: PasswordService
    ) -> None:
        """Should return False for empty hash."""
        assert password_service.verify_password("somepassword", "") is False

    def test_verify_password_returns_false_for_invalid_hash(
        self, password_service: PasswordService
    ) -> None:
        """Should return False for invalid hash format."""
        assert password_service.verify_password("somepassword", "not-a-valid-hash") is False

    def test_verify_password_handles_unicode(self, password_service: PasswordService) -> None:
        """Should handle Unicode passwords."""
        password = "пароль密码🔐"
        hash_value = password_service.hash_password(password)

        assert password_service.verify_password(password, hash_value) is True
        assert password_service.verify_password("wrongpassword", hash_value) is False

    def test_verify_password_handles_long_password(self, password_service: PasswordService) -> None:
        """Should handle long passwords."""
        password = "a" * 1000
        hash_value = password_service.hash_password(password)

        assert password_service.verify_password(password, hash_value) is True

    def test_needs_rehash_returns_false_for_current(
        self, password_service: PasswordService
    ) -> None:
        """Should return False for hashes with current parameters."""
        hash_value = password_service.hash_password("testpassword")

        assert password_service.needs_rehash(hash_value) is False

    def test_needs_rehash_returns_true_for_different_params(self) -> None:
        """Should return True for hashes with different parameters."""
        # Create hash with low cost
        old_service = PasswordService(time_cost=1, memory_cost=1024, parallelism=1)
        hash_value = old_service.hash_password("testpassword")

        # Check with higher cost service
        new_service = PasswordService(time_cost=2, memory_cost=2048, parallelism=2)
        assert new_service.needs_rehash(hash_value) is True

    def test_needs_rehash_returns_true_for_invalid_hash(
        self, password_service: PasswordService
    ) -> None:
        """Should return True for invalid hash format."""
        assert password_service.needs_rehash("not-a-valid-hash") is True


class TestPasswordServiceConfiguration:
    """Tests for custom PasswordService configuration."""

    def test_custom_time_cost(self) -> None:
        """Should use custom time cost."""
        service = PasswordService(time_cost=2, memory_cost=1024, parallelism=1)
        hash_value = service.hash_password("test")

        assert ",t=2," in hash_value

    def test_custom_memory_cost(self) -> None:
        """Should use custom memory cost."""
        service = PasswordService(time_cost=1, memory_cost=2048, parallelism=1)
        hash_value = service.hash_password("test")

        assert "$m=2048," in hash_value

    def test_custom_parallelism(self) -> None:
        """Should use custom parallelism."""
        service = PasswordService(time_cost=1, memory_cost=1024, parallelism=2)
        hash_value = service.hash_password("test")

        assert ",p=2$" in hash_value


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_hash_password_function(self) -> None:
        """Should hash password using default service."""
        hash_value = hash_password("testpassword")

        assert isinstance(hash_value, str)
        assert hash_value.startswith("$argon2id$")

    def test_verify_password_function(self) -> None:
        """Should verify password using default service."""
        password = "testpassword"
        hash_value = hash_password(password)

        assert verify_password(password, hash_value) is True
        assert verify_password("wrong", hash_value) is False

    def test_get_password_service_returns_singleton(self) -> None:
        """Should return the same instance."""
        service1 = get_password_service()
        service2 = get_password_service()

        assert service1 is service2
