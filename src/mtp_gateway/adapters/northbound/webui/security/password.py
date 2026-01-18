"""Password hashing for WebUI authentication.

Uses Argon2id algorithm - the winner of the Password Hashing Competition
and recommended for new applications. Provides secure password storage
with memory-hard hashing resistant to GPU attacks.
"""

from __future__ import annotations

import structlog
from argon2 import PasswordHasher
from argon2.exceptions import HashingError, InvalidHashError, VerifyMismatchError

logger = structlog.get_logger(__name__)


class PasswordService:
    """Service for password hashing and verification.

    Uses Argon2id with secure defaults:
    - time_cost=3: Number of iterations
    - memory_cost=65536: Memory usage in KiB (64 MiB)
    - parallelism=4: Number of parallel threads
    - hash_len=32: Length of hash output
    - salt_len=16: Length of random salt

    These parameters follow OWASP recommendations for password storage.
    """

    def __init__(
        self,
        time_cost: int = 3,
        memory_cost: int = 65536,
        parallelism: int = 4,
        hash_len: int = 32,
        salt_len: int = 16,
    ) -> None:
        """Initialize password service.

        Args:
            time_cost: Number of iterations (higher = slower/more secure)
            memory_cost: Memory usage in KiB (higher = more GPU resistant)
            parallelism: Number of parallel threads
            hash_len: Length of resulting hash in bytes
            salt_len: Length of random salt in bytes
        """
        self._hasher = PasswordHasher(
            time_cost=time_cost,
            memory_cost=memory_cost,
            parallelism=parallelism,
            hash_len=hash_len,
            salt_len=salt_len,
        )

    def hash_password(self, password: str) -> str:
        """Hash a password using Argon2id.

        Generates a secure hash with embedded parameters and random salt.
        The returned string can be stored directly in the database.

        Args:
            password: Plain text password to hash

        Returns:
            Argon2id hash string (format: $argon2id$v=19$m=65536,t=3,p=4$salt$hash)

        Raises:
            HashingError: If hashing fails
            ValueError: If password is empty
        """
        if not password:
            raise ValueError("Password cannot be empty")

        try:
            hash_value = self._hasher.hash(password)

            logger.debug(
                "Password hashed successfully",
                hash_prefix=hash_value[:20] + "...",
            )

            return hash_value

        except HashingError:
            logger.exception("Failed to hash password")
            raise

    def verify_password(self, password: str, hash_value: str) -> bool:
        """Verify a password against a stored hash.

        Performs constant-time comparison to prevent timing attacks.

        Args:
            password: Plain text password to verify
            hash_value: Stored Argon2id hash to compare against

        Returns:
            True if password matches, False otherwise
        """
        if not password or not hash_value:
            logger.debug(
                "Password verification failed - empty input",
                has_password=bool(password),
                has_hash=bool(hash_value),
            )
            return False

        try:
            self._hasher.verify(hash_value, password)
            logger.debug("Password verification successful")
            return True

        except VerifyMismatchError:
            logger.debug("Password verification failed - mismatch")
            return False

        except InvalidHashError:
            logger.warning(
                "Password verification failed - invalid hash format",
                hash_prefix=hash_value[:20] + "..." if len(hash_value) > 20 else hash_value,
            )
            return False

    def needs_rehash(self, hash_value: str) -> bool:
        """Check if a password hash needs to be rehashed.

        Returns True if the hash was created with different parameters
        than currently configured. Use this to upgrade old hashes
        when users log in.

        Args:
            hash_value: Stored Argon2id hash to check

        Returns:
            True if hash should be regenerated with new parameters
        """
        try:
            return self._hasher.check_needs_rehash(hash_value)
        except InvalidHashError:
            # Invalid hashes definitely need rehashing (after verification elsewhere)
            return True


# Default password service instance
_default_service: PasswordService | None = None


def get_password_service() -> PasswordService:
    """Get or create the default password service.

    Returns:
        Shared PasswordService instance with default settings
    """
    global _default_service  # noqa: PLW0603
    if _default_service is None:
        _default_service = PasswordService()
    return _default_service


def hash_password(password: str) -> str:
    """Convenience function to hash a password using default service.

    Args:
        password: Plain text password to hash

    Returns:
        Argon2id hash string
    """
    return get_password_service().hash_password(password)


def verify_password(password: str, hash_value: str) -> bool:
    """Convenience function to verify a password using default service.

    Args:
        password: Plain text password to verify
        hash_value: Stored hash to compare against

    Returns:
        True if password matches
    """
    return get_password_service().verify_password(password, hash_value)
