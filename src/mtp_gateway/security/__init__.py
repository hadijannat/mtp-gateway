"""Security module for MTP Gateway.

Provides:
- Certificate management for OPC UA
- Secret providers for credential management
"""

from mtp_gateway.security.certificates import CertificateManager
from mtp_gateway.security.secrets import (
    EnvironmentSecretProvider,
    SecretProvider,
)

__all__ = [
    "CertificateManager",
    "EnvironmentSecretProvider",
    "SecretProvider",
]
