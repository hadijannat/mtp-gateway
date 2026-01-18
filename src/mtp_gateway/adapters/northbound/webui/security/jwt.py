"""JWT token handling for WebUI authentication.

Provides JWT token creation and validation for access and refresh tokens.
Uses python-jose for JWT operations.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import structlog
from jose import JWTError, jwt
from pydantic import BaseModel

logger = structlog.get_logger(__name__)


class TokenPayload(BaseModel):
    """JWT token payload.

    Attributes:
        sub: Subject (username)
        exp: Expiration timestamp
        iat: Issued at timestamp
        type: Token type ("access" or "refresh")
        permissions: List of granted permissions (only for access tokens)
    """

    sub: str
    exp: datetime
    iat: datetime
    type: Literal["access", "refresh"]
    permissions: list[str] = []

    def to_jwt_claims(self) -> dict[str, Any]:
        """Convert payload to JWT claims with Unix timestamps.

        JWT requires exp and iat as Unix timestamps (numeric).

        Returns:
            Dictionary suitable for JWT encoding
        """
        return {
            "sub": self.sub,
            "exp": int(self.exp.timestamp()),
            "iat": int(self.iat.timestamp()),
            "type": self.type,
            "permissions": self.permissions,
        }


class TokenService:
    """Service for creating and validating JWT tokens.

    Handles both access tokens (short-lived, include permissions) and
    refresh tokens (longer-lived, for obtaining new access tokens).

    Attributes:
        secret: Secret key for signing tokens
        algorithm: JWT signing algorithm (default: HS256)
        access_expiry_minutes: Access token validity period
        refresh_expiry_days: Refresh token validity period
    """

    def __init__(
        self,
        secret: str,
        algorithm: str = "HS256",
        access_expiry_minutes: int = 30,
        refresh_expiry_days: int = 7,
    ) -> None:
        """Initialize token service.

        Args:
            secret: Secret key for signing tokens. Must be kept secure.
            algorithm: JWT signing algorithm (default: HS256)
            access_expiry_minutes: Access token validity in minutes (default: 30)
            refresh_expiry_days: Refresh token validity in days (default: 7)

        Raises:
            ValueError: If secret is empty or too short
        """
        if not secret or len(secret) < 32:
            raise ValueError("Secret must be at least 32 characters long")

        self._secret = secret
        self._algorithm = algorithm
        self._access_expiry_minutes = access_expiry_minutes
        self._refresh_expiry_days = refresh_expiry_days

    def create_access_token(
        self,
        username: str,
        permissions: list[str],
    ) -> str:
        """Create a new access token.

        Access tokens are short-lived and include the user's permissions.
        They should be used for authenticating API requests.

        Args:
            username: The username to encode in the token
            permissions: List of permissions granted to the user

        Returns:
            Encoded JWT access token string
        """
        now = datetime.now(UTC)
        expires = now + timedelta(minutes=self._access_expiry_minutes)

        payload = TokenPayload(
            sub=username,
            exp=expires,
            iat=now,
            type="access",
            permissions=permissions,
        )

        token: str = jwt.encode(
            payload.to_jwt_claims(),
            self._secret,
            algorithm=self._algorithm,
        )

        logger.debug(
            "Created access token",
            username=username,
            expires=expires.isoformat(),
            permission_count=len(permissions),
        )

        return token

    def create_refresh_token(self, username: str) -> str:
        """Create a new refresh token.

        Refresh tokens are longer-lived and do not include permissions.
        They should only be used to obtain new access tokens.

        Args:
            username: The username to encode in the token

        Returns:
            Encoded JWT refresh token string
        """
        now = datetime.now(UTC)
        expires = now + timedelta(days=self._refresh_expiry_days)

        payload = TokenPayload(
            sub=username,
            exp=expires,
            iat=now,
            type="refresh",
            permissions=[],
        )

        token: str = jwt.encode(
            payload.to_jwt_claims(),
            self._secret,
            algorithm=self._algorithm,
        )

        logger.debug(
            "Created refresh token",
            username=username,
            expires=expires.isoformat(),
        )

        return token

    def create_token_pair(
        self,
        username: str,
        permissions: list[str],
    ) -> tuple[str, str]:
        """Create access and refresh token pair.

        Convenience method to create both tokens at once.

        Args:
            username: The username to encode in the tokens
            permissions: List of permissions for the access token

        Returns:
            Tuple of (access_token, refresh_token)
        """
        access_token = self.create_access_token(username, permissions)
        refresh_token = self.create_refresh_token(username)

        logger.debug(
            "Created token pair",
            username=username,
        )

        return access_token, refresh_token

    def decode_token(self, token: str) -> TokenPayload:
        """Decode and validate a token.

        Validates the token signature and expiration. Returns the
        decoded payload if valid.

        Args:
            token: JWT token string to decode

        Returns:
            Decoded token payload

        Raises:
            JWTError: If token is invalid, expired, or has wrong signature
        """
        try:
            payload_dict = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
            )

            # Convert Unix timestamps back to datetime objects
            payload_dict["exp"] = datetime.fromtimestamp(payload_dict["exp"], tz=UTC)
            payload_dict["iat"] = datetime.fromtimestamp(payload_dict["iat"], tz=UTC)

            # Parse the payload into our model
            payload = TokenPayload.model_validate(payload_dict)

            logger.debug(
                "Decoded token",
                username=payload.sub,
                type=payload.type,
            )

            return payload

        except JWTError:
            logger.warning(
                "Failed to decode token",
                error_type="jwt_decode_error",
            )
            raise

    def is_token_valid(self, token: str) -> bool:
        """Check if token is valid without raising exceptions.

        Useful for optional authentication scenarios where an invalid
        token should not cause an error.

        Args:
            token: JWT token string to validate

        Returns:
            True if token is valid, False otherwise
        """
        try:
            self.decode_token(token)
            return True
        except JWTError:
            return False
