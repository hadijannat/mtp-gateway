"""Certificate management for OPC UA security.

Provides self-signed certificate generation and management for the
MTP Gateway OPC UA server and client connections.
"""

from __future__ import annotations

import ipaddress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

logger = structlog.get_logger(__name__)

# Default certificate validity
DEFAULT_VALIDITY_DAYS = 365

# Default RSA key size
DEFAULT_KEY_SIZE = 2048


class CertificateManager:
    """Manager for OPC UA certificates.

    Handles generation, loading, and validation of certificates
    used for OPC UA secure communication.
    """

    def __init__(self, cert_dir: Path | None = None) -> None:
        """Initialize the certificate manager.

        Args:
            cert_dir: Directory for storing certificates. If None,
                      uses current working directory.
        """
        self._cert_dir = cert_dir or Path.cwd()

    async def generate_self_signed(
        self,
        common_name: str,
        validity_days: int = DEFAULT_VALIDITY_DAYS,
        *,
        organization: str = "MTP Gateway",
        application_uri: str | None = None,
        dns_names: list[str] | None = None,
        ip_addresses: list[str] | None = None,
        for_server: bool = True,
        for_client: bool = False,
    ) -> tuple[Path, Path]:
        """Generate a self-signed certificate and private key.

        Args:
            common_name: Common name for the certificate (e.g., hostname).
            validity_days: Number of days the certificate is valid.
            organization: Organization name in the certificate subject.
            application_uri: OPC UA application URI for the certificate.
            dns_names: Additional DNS names for Subject Alternative Names.
            ip_addresses: IP addresses for Subject Alternative Names.
            for_server: Include server authentication extended key usage.
            for_client: Include client authentication extended key usage.

        Returns:
            Tuple of (certificate_path, key_path).
        """
        logger.info(
            "Generating self-signed certificate",
            common_name=common_name,
            validity_days=validity_days,
            organization=organization,
        )

        # Ensure directory exists
        self._cert_dir.mkdir(parents=True, exist_ok=True)

        # Generate private key
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=DEFAULT_KEY_SIZE,
        )

        # Build subject
        subject = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, organization),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ])

        # Build certificate
        now = datetime.now(UTC)
        builder = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)  # Self-signed
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + timedelta(days=validity_days))
        )

        # Add Subject Alternative Names
        san_entries: list[x509.GeneralName] = []

        # Add DNS names
        san_entries.append(x509.DNSName(common_name))
        for dns_name in dns_names or []:
            san_entries.append(x509.DNSName(dns_name))

        # Add IP addresses
        for ip_str in ip_addresses or []:
            try:
                ip_addr = ipaddress.ip_address(ip_str)
                san_entries.append(x509.IPAddress(ip_addr))
            except ValueError:
                logger.warning("Invalid IP address in SAN", ip=ip_str)

        # Add application URI if provided
        if application_uri:
            san_entries.append(x509.UniformResourceIdentifier(application_uri))

        if san_entries:
            builder = builder.add_extension(
                x509.SubjectAlternativeName(san_entries),
                critical=False,
            )

        # Add Extended Key Usage
        key_usages: list[x509.ObjectIdentifier] = []
        if for_server:
            key_usages.append(ExtendedKeyUsageOID.SERVER_AUTH)
        if for_client:
            key_usages.append(ExtendedKeyUsageOID.CLIENT_AUTH)

        if key_usages:
            builder = builder.add_extension(
                x509.ExtendedKeyUsage(key_usages),
                critical=False,
            )

        # Add Basic Constraints (CA: false for end-entity)
        builder = builder.add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )

        # Add Key Usage
        builder = builder.add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )

        # Add Subject Key Identifier
        builder = builder.add_extension(
            x509.SubjectKeyIdentifier.from_public_key(private_key.public_key()),
            critical=False,
        )

        # Sign the certificate
        certificate = builder.sign(private_key, hashes.SHA256())

        # Write files
        cert_path = self._cert_dir / f"{common_name}.der"
        key_path = self._cert_dir / f"{common_name}.pem"

        # Write certificate in DER format (OPC UA standard)
        cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.DER))

        # Write private key in PEM format
        key_path.write_bytes(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

        logger.info(
            "Certificate generated",
            cert_path=str(cert_path),
            key_path=str(key_path),
        )

        return cert_path, key_path

    async def load_or_generate(
        self,
        cert_path: Path,
        key_path: Path,
        common_name: str,
        **kwargs: object,
    ) -> tuple[Path, Path]:
        """Load existing certificate or generate a new one.

        Args:
            cert_path: Path to the certificate file.
            key_path: Path to the private key file.
            common_name: Common name for generation if needed.
            **kwargs: Additional arguments passed to generate_self_signed.

        Returns:
            Tuple of (certificate_path, key_path).
        """
        if cert_path.exists() and key_path.exists():
            # Verify certificate is still valid
            expiry = self.check_expiry(cert_path)
            if expiry > datetime.now(UTC):
                logger.info("Using existing certificate", cert_path=str(cert_path))
                return cert_path, key_path
            logger.warning("Certificate expired, regenerating", expiry=expiry)

        # Generate new certificate
        self._cert_dir = cert_path.parent
        generated_cert, generated_key = await self.generate_self_signed(
            common_name=common_name,
            **kwargs,  # type: ignore[arg-type]
        )

        # Rename to requested paths if different
        if generated_cert != cert_path:
            generated_cert.rename(cert_path)
        if generated_key != key_path:
            generated_key.rename(key_path)

        return cert_path, key_path

    def check_expiry(self, cert_path: Path) -> datetime:
        """Check certificate expiry date.

        Args:
            cert_path: Path to the certificate file.

        Returns:
            Expiry datetime in UTC.

        Raises:
            ValueError: If certificate cannot be loaded.
        """
        cert_bytes = cert_path.read_bytes()

        # Try DER format first (OPC UA standard), then PEM
        try:
            cert = x509.load_der_x509_certificate(cert_bytes)
        except ValueError:
            cert = x509.load_pem_x509_certificate(cert_bytes)

        # Ensure timezone-aware datetime
        expiry = cert.not_valid_after_utc
        return expiry

    def get_certificate_info(self, cert_path: Path) -> dict[str, object]:
        """Get certificate information.

        Args:
            cert_path: Path to the certificate file.

        Returns:
            Dictionary with certificate details.
        """
        cert_bytes = cert_path.read_bytes()

        try:
            cert = x509.load_der_x509_certificate(cert_bytes)
        except ValueError:
            cert = x509.load_pem_x509_certificate(cert_bytes)

        # Extract subject fields
        subject_dict: dict[str, str] = {}
        for attr in cert.subject:
            oid_name = getattr(attr.oid, "_name", str(attr.oid))
            subject_dict[oid_name] = str(attr.value)

        return {
            "subject": subject_dict,
            "issuer": {
                getattr(attr.oid, "_name", str(attr.oid)): str(attr.value)
                for attr in cert.issuer
            },
            "serial_number": cert.serial_number,
            "not_valid_before": cert.not_valid_before_utc,
            "not_valid_after": cert.not_valid_after_utc,
            "version": cert.version.name,
        }


def load_private_key(key_path: Path, password: bytes | None = None) -> RSAPrivateKey:
    """Load a private key from file.

    Args:
        key_path: Path to the private key file.
        password: Optional password for encrypted keys.

    Returns:
        The loaded private key.
    """
    key_bytes = key_path.read_bytes()
    return serialization.load_pem_private_key(key_bytes, password=password)  # type: ignore[return-value]
