"""Tests for WebUI JWT token handling.

Tests for:
- Token creation (access and refresh)
- Token validation and decoding
- Token expiration
- Error handling for invalid tokens
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from jose import JWTError, jwt

from mtp_gateway.adapters.northbound.webui.security.jwt import (
    TokenPayload,
    TokenService,
)

# Filter python-jose deprecation warning about datetime.utcnow()
pytestmark = pytest.mark.filterwarnings(
    "ignore:datetime.datetime.utcnow\\(\\) is deprecated:DeprecationWarning"
)


class TestTokenService:
    """Tests for TokenService."""

    @pytest.fixture
    def secret(self) -> str:
        """Return a valid secret for testing."""
        return "test-secret-key-that-is-at-least-32-characters-long"

    @pytest.fixture
    def token_service(self, secret: str) -> TokenService:
        """Create a TokenService instance for testing."""
        return TokenService(
            secret=secret,
            algorithm="HS256",
            access_expiry_minutes=30,
            refresh_expiry_days=7,
        )

    def test_init_rejects_short_secret(self) -> None:
        """Should reject secrets shorter than 32 characters."""
        with pytest.raises(ValueError, match="at least 32 characters"):
            TokenService(secret="short-secret")

    def test_init_rejects_empty_secret(self) -> None:
        """Should reject empty secrets."""
        with pytest.raises(ValueError, match="at least 32 characters"):
            TokenService(secret="")

    def test_init_accepts_valid_secret(self, secret: str) -> None:
        """Should accept secrets of valid length."""
        service = TokenService(secret=secret)
        assert service is not None

    def test_create_access_token_returns_string(self, token_service: TokenService) -> None:
        """Should return a JWT token string."""
        token = token_service.create_access_token(
            username="testuser",
            permissions=["read", "write"],
        )

        assert isinstance(token, str)
        assert len(token) > 0
        # JWT tokens have 3 parts separated by dots
        assert token.count(".") == 2

    def test_create_access_token_encodes_username(self, token_service: TokenService) -> None:
        """Should encode the username in the token."""
        token = token_service.create_access_token(
            username="admin",
            permissions=[],
        )

        payload = token_service.decode_token(token)
        assert payload.sub == "admin"

    def test_create_access_token_encodes_permissions(self, token_service: TokenService) -> None:
        """Should encode permissions in access token."""
        permissions = ["read:tags", "write:tags", "admin"]
        token = token_service.create_access_token(
            username="testuser",
            permissions=permissions,
        )

        payload = token_service.decode_token(token)
        assert payload.permissions == permissions

    def test_create_access_token_sets_type(self, token_service: TokenService) -> None:
        """Should set token type to 'access'."""
        token = token_service.create_access_token(
            username="testuser",
            permissions=[],
        )

        payload = token_service.decode_token(token)
        assert payload.type == "access"

    def test_create_access_token_sets_expiration(self, token_service: TokenService) -> None:
        """Should set expiration based on access_expiry_minutes."""
        before = datetime.now(UTC)
        token = token_service.create_access_token(
            username="testuser",
            permissions=[],
        )
        after = datetime.now(UTC)

        payload = token_service.decode_token(token)

        # Expiration should be about 30 minutes from now
        # Note: JWT uses integer timestamps, so we lose sub-second precision
        expected_min = before + timedelta(minutes=30) - timedelta(seconds=1)
        expected_max = after + timedelta(minutes=30) + timedelta(seconds=1)

        assert expected_min <= payload.exp <= expected_max

    def test_create_access_token_sets_issued_at(self, token_service: TokenService) -> None:
        """Should set issued at timestamp."""
        before = datetime.now(UTC)
        token = token_service.create_access_token(
            username="testuser",
            permissions=[],
        )
        after = datetime.now(UTC)

        payload = token_service.decode_token(token)

        # iat should be between before and after
        # Note: JWT uses integer timestamps, so we lose sub-second precision
        assert before - timedelta(seconds=1) <= payload.iat <= after + timedelta(seconds=1)

    def test_create_refresh_token_returns_string(self, token_service: TokenService) -> None:
        """Should return a JWT token string."""
        token = token_service.create_refresh_token(username="testuser")

        assert isinstance(token, str)
        assert len(token) > 0
        assert token.count(".") == 2

    def test_create_refresh_token_encodes_username(self, token_service: TokenService) -> None:
        """Should encode the username in the token."""
        token = token_service.create_refresh_token(username="admin")

        payload = token_service.decode_token(token)
        assert payload.sub == "admin"

    def test_create_refresh_token_has_empty_permissions(self, token_service: TokenService) -> None:
        """Refresh tokens should not include permissions."""
        token = token_service.create_refresh_token(username="testuser")

        payload = token_service.decode_token(token)
        assert payload.permissions == []

    def test_create_refresh_token_sets_type(self, token_service: TokenService) -> None:
        """Should set token type to 'refresh'."""
        token = token_service.create_refresh_token(username="testuser")

        payload = token_service.decode_token(token)
        assert payload.type == "refresh"

    def test_create_refresh_token_sets_longer_expiration(self, token_service: TokenService) -> None:
        """Should set expiration based on refresh_expiry_days."""
        before = datetime.now(UTC)
        token = token_service.create_refresh_token(username="testuser")
        after = datetime.now(UTC)

        payload = token_service.decode_token(token)

        # Expiration should be about 7 days from now
        # Note: JWT uses integer timestamps, so we lose sub-second precision
        expected_min = before + timedelta(days=7) - timedelta(seconds=1)
        expected_max = after + timedelta(days=7) + timedelta(seconds=1)

        assert expected_min <= payload.exp <= expected_max

    def test_create_token_pair_returns_both_tokens(self, token_service: TokenService) -> None:
        """Should return tuple of access and refresh tokens."""
        access_token, refresh_token = token_service.create_token_pair(
            username="testuser",
            permissions=["read"],
        )

        assert isinstance(access_token, str)
        assert isinstance(refresh_token, str)
        assert access_token != refresh_token

    def test_create_token_pair_access_has_permissions(self, token_service: TokenService) -> None:
        """Access token from pair should include permissions."""
        permissions = ["read", "write"]
        access_token, _ = token_service.create_token_pair(
            username="testuser",
            permissions=permissions,
        )

        payload = token_service.decode_token(access_token)
        assert payload.type == "access"
        assert payload.permissions == permissions

    def test_create_token_pair_refresh_has_no_permissions(
        self, token_service: TokenService
    ) -> None:
        """Refresh token from pair should not include permissions."""
        _, refresh_token = token_service.create_token_pair(
            username="testuser",
            permissions=["read", "write"],
        )

        payload = token_service.decode_token(refresh_token)
        assert payload.type == "refresh"
        assert payload.permissions == []

    def test_decode_token_returns_payload(self, token_service: TokenService) -> None:
        """Should decode token and return TokenPayload."""
        token = token_service.create_access_token(
            username="testuser",
            permissions=["read"],
        )

        payload = token_service.decode_token(token)

        assert isinstance(payload, TokenPayload)
        assert payload.sub == "testuser"

    def test_decode_token_raises_on_invalid_signature(self, token_service: TokenService) -> None:
        """Should raise JWTError for tokens with wrong signature."""
        # Create token with different secret
        other_service = TokenService(secret="different-secret-that-is-32-chars-plus")
        token = other_service.create_access_token(
            username="testuser",
            permissions=[],
        )

        with pytest.raises(JWTError):
            token_service.decode_token(token)

    def test_decode_token_raises_on_expired_token(self, secret: str) -> None:
        """Should raise JWTError for expired tokens."""
        # Create service with very short expiry
        service = TokenService(
            secret=secret,
            access_expiry_minutes=0,  # Immediate expiration
        )

        # Create token that expires immediately
        now = datetime.now(UTC)
        expired_payload = {
            "sub": "testuser",
            "exp": (now - timedelta(seconds=10)).timestamp(),
            "iat": (now - timedelta(minutes=5)).timestamp(),
            "type": "access",
            "permissions": [],
        }
        expired_token = jwt.encode(expired_payload, secret, algorithm="HS256")

        with pytest.raises(JWTError):
            service.decode_token(expired_token)

    def test_decode_token_raises_on_malformed_token(self, token_service: TokenService) -> None:
        """Should raise JWTError for malformed tokens."""
        with pytest.raises(JWTError):
            token_service.decode_token("not.a.validtoken")

    def test_decode_token_raises_on_empty_token(self, token_service: TokenService) -> None:
        """Should raise JWTError for empty tokens."""
        with pytest.raises(JWTError):
            token_service.decode_token("")

    def test_is_token_valid_returns_true_for_valid_token(self, token_service: TokenService) -> None:
        """Should return True for valid tokens."""
        token = token_service.create_access_token(
            username="testuser",
            permissions=[],
        )

        assert token_service.is_token_valid(token) is True

    def test_is_token_valid_returns_false_for_invalid_token(
        self, token_service: TokenService
    ) -> None:
        """Should return False for invalid tokens."""
        assert token_service.is_token_valid("invalid.token.here") is False

    def test_is_token_valid_returns_false_for_expired_token(self, secret: str) -> None:
        """Should return False for expired tokens."""
        service = TokenService(secret=secret)

        # Create expired token manually
        now = datetime.now(UTC)
        expired_payload = {
            "sub": "testuser",
            "exp": (now - timedelta(seconds=10)).timestamp(),
            "iat": (now - timedelta(minutes=5)).timestamp(),
            "type": "access",
            "permissions": [],
        }
        expired_token = jwt.encode(expired_payload, secret, algorithm="HS256")

        assert service.is_token_valid(expired_token) is False

    def test_is_token_valid_returns_false_for_wrong_signature(
        self, token_service: TokenService
    ) -> None:
        """Should return False for tokens signed with wrong key."""
        other_service = TokenService(secret="different-secret-that-is-32-chars-plus")
        token = other_service.create_access_token(
            username="testuser",
            permissions=[],
        )

        assert token_service.is_token_valid(token) is False


class TestTokenPayload:
    """Tests for TokenPayload model."""

    def test_token_payload_required_fields(self) -> None:
        """Should require sub, exp, iat, and type fields."""
        now = datetime.now(UTC)
        payload = TokenPayload(
            sub="testuser",
            exp=now + timedelta(hours=1),
            iat=now,
            type="access",
        )

        assert payload.sub == "testuser"
        assert payload.type == "access"
        assert payload.permissions == []  # Default value

    def test_token_payload_with_permissions(self) -> None:
        """Should accept permissions list."""
        now = datetime.now(UTC)
        permissions = ["read:tags", "write:config"]
        payload = TokenPayload(
            sub="admin",
            exp=now + timedelta(hours=1),
            iat=now,
            type="access",
            permissions=permissions,
        )

        assert payload.permissions == permissions

    def test_token_payload_type_literal(self) -> None:
        """Should only accept 'access' or 'refresh' as type."""
        now = datetime.now(UTC)

        # Valid types
        access = TokenPayload(sub="user", exp=now, iat=now, type="access")
        refresh = TokenPayload(sub="user", exp=now, iat=now, type="refresh")

        assert access.type == "access"
        assert refresh.type == "refresh"


class TestTokenServiceCustomConfiguration:
    """Tests for custom TokenService configuration."""

    def test_custom_algorithm(self) -> None:
        """Should use custom algorithm."""
        secret = "test-secret-key-that-is-at-least-32-characters-long"
        service = TokenService(
            secret=secret,
            algorithm="HS384",
        )

        token = service.create_access_token(
            username="testuser",
            permissions=[],
        )

        # Should decode successfully with same algorithm
        payload = service.decode_token(token)
        assert payload.sub == "testuser"

    def test_custom_access_expiry(self) -> None:
        """Should use custom access token expiry."""
        secret = "test-secret-key-that-is-at-least-32-characters-long"
        service = TokenService(
            secret=secret,
            access_expiry_minutes=60,  # 1 hour
        )

        before = datetime.now(UTC)
        token = service.create_access_token(
            username="testuser",
            permissions=[],
        )

        payload = service.decode_token(token)

        # Expiration should be about 60 minutes from now
        expected = before + timedelta(minutes=60)
        # Allow 5 second tolerance
        assert abs((payload.exp - expected).total_seconds()) < 5

    def test_custom_refresh_expiry(self) -> None:
        """Should use custom refresh token expiry."""
        secret = "test-secret-key-that-is-at-least-32-characters-long"
        service = TokenService(
            secret=secret,
            refresh_expiry_days=30,  # 30 days
        )

        before = datetime.now(UTC)
        token = service.create_refresh_token(username="testuser")

        payload = service.decode_token(token)

        # Expiration should be about 30 days from now
        expected = before + timedelta(days=30)
        # Allow 5 second tolerance
        assert abs((payload.exp - expected).total_seconds()) < 5
