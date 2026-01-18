"""Secret providers for secure credential management.

Provides abstractions for retrieving secrets from various sources:
- Environment variables (default, suitable for containers)
- HashiCorp Vault (enterprise deployments)

Secrets are never logged - the audit module masks sensitive values.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import structlog

if TYPE_CHECKING:
    import hvac

logger = structlog.get_logger(__name__)

# Keys that should be masked in logs
SENSITIVE_KEYS = frozenset(
    {
        "password",
        "secret",
        "token",
        "key",
        "api_key",
        "apikey",
        "credential",
        "auth",
        "private",
    }
)


def is_sensitive_key(key: str) -> bool:
    """Check if a key name suggests sensitive content.

    Args:
        key: The key name to check.

    Returns:
        True if the key appears to be sensitive.
    """
    key_lower = key.lower()
    return any(sensitive in key_lower for sensitive in SENSITIVE_KEYS)


def mask_sensitive_value(value: str) -> str:
    """Mask a sensitive value for safe logging.

    Args:
        value: The value to mask.

    Returns:
        Masked version of the value.
    """
    if len(value) <= 4:
        return "****"
    return value[:2] + "****" + value[-2:]


@runtime_checkable
class SecretProvider(Protocol):
    """Protocol for secret providers.

    Implementations must provide async methods for retrieving secrets.
    This allows for different backends (env vars, Vault, AWS Secrets Manager, etc.)
    """

    async def get_secret(self, key: str) -> str | None:
        """Retrieve a secret by key.

        Args:
            key: The secret key/name.

        Returns:
            The secret value, or None if not found.
        """
        ...

    async def get_secret_or_raise(self, key: str) -> str:
        """Retrieve a secret by key, raising if not found.

        Args:
            key: The secret key/name.

        Returns:
            The secret value.

        Raises:
            SecretNotFoundError: If the secret is not found.
        """
        ...


class SecretNotFoundError(Exception):
    """Raised when a required secret is not found."""

    def __init__(self, key: str, provider: str) -> None:
        self.key = key
        self.provider = provider
        super().__init__(f"Secret '{key}' not found in {provider}")


class BaseSecretProvider(ABC):
    """Base class for secret providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the provider for logging."""
        ...

    @abstractmethod
    async def get_secret(self, key: str) -> str | None:
        """Retrieve a secret by key."""
        ...

    async def get_secret_or_raise(self, key: str) -> str:
        """Retrieve a secret by key, raising if not found."""
        value = await self.get_secret(key)
        if value is None:
            raise SecretNotFoundError(key, self.provider_name)
        return value


class EnvironmentSecretProvider(BaseSecretProvider):
    """Secret provider that reads from environment variables.

    This is the default provider, suitable for:
    - Container deployments (Docker, Kubernetes)
    - Local development
    - CI/CD environments

    Secrets are expected as environment variables with an optional prefix.
    For example, with prefix "MTP_", the key "db_password" becomes "MTP_DB_PASSWORD".
    """

    def __init__(self, prefix: str = "MTP_") -> None:
        """Initialize the environment secret provider.

        Args:
            prefix: Prefix for environment variable names.
        """
        self._prefix = prefix.upper()

    @property
    def provider_name(self) -> str:
        return "environment"

    def _get_env_key(self, key: str) -> str:
        """Convert a secret key to environment variable name.

        Args:
            key: The secret key.

        Returns:
            The environment variable name.
        """
        return f"{self._prefix}{key.upper()}"

    async def get_secret(self, key: str) -> str | None:
        """Retrieve a secret from environment variables.

        Args:
            key: The secret key (will be uppercased with prefix).

        Returns:
            The secret value, or None if not set.
        """
        env_key = self._get_env_key(key)
        value = os.environ.get(env_key)

        if value is not None:
            # Log access but mask value
            logger.debug(
                "Secret retrieved from environment",
                key=key,
                env_key=env_key,
                masked_value=mask_sensitive_value(value) if is_sensitive_key(key) else "[value]",
            )
        else:
            logger.debug("Secret not found in environment", key=key, env_key=env_key)

        return value

    def list_available_keys(self) -> list[str]:
        """List all environment variables matching the prefix.

        Returns:
            List of keys (without prefix) that are set.
        """
        keys = []
        for env_key in os.environ:
            if env_key.startswith(self._prefix):
                key = env_key[len(self._prefix) :].lower()
                keys.append(key)
        return keys


class VaultSecretProvider(BaseSecretProvider):
    """Secret provider that reads from HashiCorp Vault.

    Suitable for enterprise deployments with centralized secret management.
    Requires the `hvac` package to be installed.

    Note: This is a placeholder implementation. A production implementation
    would include:
    - Token refresh and rotation
    - Connection pooling
    - Caching with TTL
    - Health checks
    """

    def __init__(
        self,
        vault_url: str,
        vault_token: str | None = None,
        mount_point: str = "secret",
        path_prefix: str = "mtp-gateway/",
    ) -> None:
        """Initialize the Vault secret provider.

        Args:
            vault_url: Vault server URL.
            vault_token: Vault authentication token.
                        If None, reads from VAULT_TOKEN environment variable.
            mount_point: Vault secrets engine mount point.
            path_prefix: Path prefix for secrets in Vault.
        """
        self._vault_url = vault_url
        self._vault_token = vault_token or os.environ.get("VAULT_TOKEN")
        self._mount_point = mount_point
        self._path_prefix = path_prefix
        self._client: object | None = None

    @property
    def provider_name(self) -> str:
        return f"vault ({self._vault_url})"

    def _get_client(self) -> hvac.Client:
        """Get or create Vault client."""
        if self._client is None:
            try:
                import hvac as hvac_module  # noqa: PLC0415
            except ImportError as e:
                raise RuntimeError(
                    "hvac package required for Vault support. Install with: pip install hvac"
                ) from e

            self._client = hvac_module.Client(url=self._vault_url, token=self._vault_token)
        return self._client  # type: ignore[return-value]

    async def get_secret(self, key: str) -> str | None:
        """Retrieve a secret from Vault.

        Args:
            key: The secret key.

        Returns:
            The secret value, or None if not found.
        """
        try:
            client = self._get_client()
            path = f"{self._path_prefix}{key}"

            # Use KV v2 API
            response = client.secrets.kv.v2.read_secret_version(  # type: ignore[union-attr]
                path=path,
                mount_point=self._mount_point,
            )

            value = response.get("data", {}).get("data", {}).get("value")

            if value is not None:
                masked = mask_sensitive_value(value) if is_sensitive_key(key) else "[value]"
                logger.debug(
                    "Secret retrieved from Vault",
                    key=key,
                    path=path,
                    masked_value=masked,
                )
            else:
                logger.debug("Secret not found in Vault", key=key, path=path)

            return value

        except Exception as e:
            logger.warning(
                "Failed to retrieve secret from Vault",
                key=key,
                error=str(e),
            )
            return None


class CompositeSecretProvider(BaseSecretProvider):
    """Secret provider that chains multiple providers.

    Tries each provider in order until a secret is found.
    Useful for fallback patterns (e.g., try Vault, fall back to env).
    """

    def __init__(self, providers: list[BaseSecretProvider]) -> None:
        """Initialize with a list of providers.

        Args:
            providers: List of providers to try in order.
        """
        if not providers:
            raise ValueError("At least one provider is required")
        self._providers = providers

    @property
    def provider_name(self) -> str:
        names = [p.provider_name for p in self._providers]
        return f"composite ({', '.join(names)})"

    async def get_secret(self, key: str) -> str | None:
        """Retrieve a secret, trying each provider in order.

        Args:
            key: The secret key.

        Returns:
            The secret value from the first provider that has it,
            or None if no provider has the secret.
        """
        for provider in self._providers:
            value = await provider.get_secret(key)
            if value is not None:
                return value
        return None


# Default provider instance for convenience
_default_provider: BaseSecretProvider | None = None


def get_default_provider() -> BaseSecretProvider:
    """Get the default secret provider.

    Returns:
        The default EnvironmentSecretProvider instance.
    """
    global _default_provider  # noqa: PLW0603
    if _default_provider is None:
        _default_provider = EnvironmentSecretProvider()
    return _default_provider


def set_default_provider(provider: BaseSecretProvider) -> None:
    """Set the default secret provider.

    Args:
        provider: The provider to use as default.
    """
    global _default_provider  # noqa: PLW0603
    _default_provider = provider


async def get_secret(key: str) -> str | None:
    """Convenience function to get a secret using the default provider.

    Args:
        key: The secret key.

    Returns:
        The secret value, or None if not found.
    """
    return await get_default_provider().get_secret(key)
