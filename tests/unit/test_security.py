"""Tests for security module.

Tests for:
- Certificate generation and management
- Secret providers (environment, vault)
- Security audit logging
- Sensitive value masking
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from mtp_gateway.application.audit import AuditTrail, SecurityAuditEntry
from mtp_gateway.security.certificates import CertificateManager
from mtp_gateway.security.secrets import (
    CompositeSecretProvider,
    EnvironmentSecretProvider,
    SecretNotFoundError,
    is_sensitive_key,
    mask_sensitive_value,
)

if TYPE_CHECKING:
    pass


class TestCertificateManager:
    """Tests for CertificateManager."""

    @pytest.fixture
    def cert_dir(self, tmp_path: Path) -> Path:
        """Create a temporary directory for certificates."""
        cert_dir = tmp_path / "certs"
        cert_dir.mkdir()
        return cert_dir

    @pytest.mark.asyncio
    async def test_generate_self_signed_creates_files(self, cert_dir: Path) -> None:
        """Should create certificate and key files."""
        manager = CertificateManager(cert_dir=cert_dir)

        cert_path, key_path = await manager.generate_self_signed(
            common_name="test-server",
            validity_days=365,
        )

        assert cert_path.exists()
        assert key_path.exists()
        assert cert_path.suffix == ".der"
        assert key_path.suffix == ".pem"

    @pytest.mark.asyncio
    async def test_generate_self_signed_with_custom_params(self, cert_dir: Path) -> None:
        """Should generate certificate with custom parameters."""
        manager = CertificateManager(cert_dir=cert_dir)

        cert_path, key_path = await manager.generate_self_signed(
            common_name="custom-server",
            validity_days=30,
            organization="Test Organization",
            application_uri="urn:test:application",
            dns_names=["localhost", "test.local"],
            ip_addresses=["127.0.0.1", "192.168.1.1"],
            for_server=True,
            for_client=True,
        )

        assert cert_path.exists()
        assert key_path.exists()

    @pytest.mark.asyncio
    async def test_check_expiry_returns_future_date(self, cert_dir: Path) -> None:
        """Should return expiry date in the future for new certificate."""
        manager = CertificateManager(cert_dir=cert_dir)

        cert_path, _ = await manager.generate_self_signed(
            common_name="expiry-test",
            validity_days=365,
        )

        expiry = manager.check_expiry(cert_path)

        assert expiry > datetime.now(UTC)
        assert expiry < datetime.now(UTC) + timedelta(days=366)

    @pytest.mark.asyncio
    async def test_get_certificate_info(self, cert_dir: Path) -> None:
        """Should return certificate information."""
        manager = CertificateManager(cert_dir=cert_dir)

        cert_path, _ = await manager.generate_self_signed(
            common_name="info-test",
            organization="Test Org",
            validity_days=365,
        )

        info = manager.get_certificate_info(cert_path)

        assert "subject" in info
        assert "issuer" in info
        assert "serial_number" in info
        assert "not_valid_before" in info
        assert "not_valid_after" in info

    @pytest.mark.asyncio
    async def test_load_or_generate_creates_new(self, cert_dir: Path) -> None:
        """Should generate new certificate if none exists."""
        manager = CertificateManager(cert_dir=cert_dir)
        cert_path = cert_dir / "new.der"
        key_path = cert_dir / "new.pem"

        result_cert, result_key = await manager.load_or_generate(
            cert_path=cert_path,
            key_path=key_path,
            common_name="new-cert",
        )

        assert result_cert.exists()
        assert result_key.exists()

    @pytest.mark.asyncio
    async def test_load_or_generate_uses_existing(self, cert_dir: Path) -> None:
        """Should use existing certificate if valid."""
        manager = CertificateManager(cert_dir=cert_dir)

        # Generate initial certificate
        cert_path, key_path = await manager.generate_self_signed(
            common_name="existing-test",
            validity_days=365,
        )

        # Record modification time
        original_mtime = cert_path.stat().st_mtime

        # Load or generate should use existing
        result_cert, result_key = await manager.load_or_generate(
            cert_path=cert_path,
            key_path=key_path,
            common_name="existing-test",
        )

        # Should not have regenerated
        assert result_cert.stat().st_mtime == original_mtime


class TestSecretProviders:
    """Tests for secret provider implementations."""

    @pytest.mark.asyncio
    async def test_environment_provider_gets_secret(self) -> None:
        """Should retrieve secret from environment variable."""
        provider = EnvironmentSecretProvider(prefix="TEST_")

        with patch.dict(os.environ, {"TEST_DB_PASSWORD": "secret123"}):
            value = await provider.get_secret("db_password")

        assert value == "secret123"

    @pytest.mark.asyncio
    async def test_environment_provider_returns_none_for_missing(self) -> None:
        """Should return None for missing secret."""
        provider = EnvironmentSecretProvider(prefix="TEST_")

        value = await provider.get_secret("nonexistent_key")

        assert value is None

    @pytest.mark.asyncio
    async def test_environment_provider_get_or_raise(self) -> None:
        """Should raise SecretNotFoundError when secret is missing."""
        provider = EnvironmentSecretProvider(prefix="TEST_")

        with pytest.raises(SecretNotFoundError) as exc_info:
            await provider.get_secret_or_raise("missing_secret")

        assert "missing_secret" in str(exc_info.value)
        assert "environment" in str(exc_info.value)

    def test_environment_provider_list_available_keys(self) -> None:
        """Should list available keys with matching prefix."""
        provider = EnvironmentSecretProvider(prefix="TESTLIST_")

        with patch.dict(
            os.environ,
            {
                "TESTLIST_KEY1": "value1",
                "TESTLIST_KEY2": "value2",
                "OTHER_KEY": "other",
            },
            clear=False,
        ):
            keys = provider.list_available_keys()

        assert "key1" in keys
        assert "key2" in keys
        assert "other_key" not in keys

    @pytest.mark.asyncio
    async def test_composite_provider_tries_providers_in_order(self) -> None:
        """Should try providers in order until secret is found."""
        provider1 = EnvironmentSecretProvider(prefix="FIRST_")
        provider2 = EnvironmentSecretProvider(prefix="SECOND_")
        composite = CompositeSecretProvider([provider1, provider2])

        with patch.dict(os.environ, {"SECOND_MY_SECRET": "from_second"}):
            value = await composite.get_secret("my_secret")

        assert value == "from_second"

    @pytest.mark.asyncio
    async def test_composite_provider_uses_first_match(self) -> None:
        """Should use first provider that has the secret."""
        provider1 = EnvironmentSecretProvider(prefix="FIRST_")
        provider2 = EnvironmentSecretProvider(prefix="SECOND_")
        composite = CompositeSecretProvider([provider1, provider2])

        with patch.dict(
            os.environ,
            {
                "FIRST_MY_SECRET": "from_first",
                "SECOND_MY_SECRET": "from_second",
            },
        ):
            value = await composite.get_secret("my_secret")

        assert value == "from_first"


class TestSensitiveValueHandling:
    """Tests for sensitive value masking."""

    def test_is_sensitive_key_detects_password(self) -> None:
        """Should detect password keys as sensitive."""
        assert is_sensitive_key("password") is True
        assert is_sensitive_key("user_password") is True
        assert is_sensitive_key("PASSWORD") is True
        assert is_sensitive_key("db_password_hash") is True

    def test_is_sensitive_key_detects_token(self) -> None:
        """Should detect token keys as sensitive."""
        assert is_sensitive_key("token") is True
        assert is_sensitive_key("api_token") is True
        assert is_sensitive_key("access_token") is True

    def test_is_sensitive_key_detects_secret(self) -> None:
        """Should detect secret keys as sensitive."""
        assert is_sensitive_key("secret") is True
        assert is_sensitive_key("client_secret") is True

    def test_is_sensitive_key_allows_safe_keys(self) -> None:
        """Should not flag safe keys as sensitive."""
        assert is_sensitive_key("username") is False
        assert is_sensitive_key("email") is False
        assert is_sensitive_key("config_path") is False

    def test_mask_sensitive_value_masks_long_values(self) -> None:
        """Should mask long values with partial visibility."""
        masked = mask_sensitive_value("mysupersecretvalue")

        assert masked == "my****ue"
        assert "supersecret" not in masked

    def test_mask_sensitive_value_masks_short_values(self) -> None:
        """Should fully mask short values."""
        masked = mask_sensitive_value("abc")

        assert masked == "****"


class TestSecurityAuditLogging:
    """Tests for security event audit logging."""

    @pytest.mark.asyncio
    async def test_log_security_event_creates_entry(self) -> None:
        """Should create security audit entry."""
        audit = AuditTrail()

        await audit.log_security_event(
            event_type="cert_generated",
            details={"common_name": "test-server"},
            success=True,
        )

        entries = audit.get_entries()
        assert len(entries) == 1
        assert isinstance(entries[0], SecurityAuditEntry)
        assert entries[0].event_type == "cert_generated"
        assert entries[0].success is True

    @pytest.mark.asyncio
    async def test_log_security_event_with_source_ip(self) -> None:
        """Should log security event with source IP."""
        audit = AuditTrail()

        await audit.log_security_event(
            event_type="auth_failure",
            details={"username": "admin"},
            success=False,
            source_ip="192.168.1.100",
        )

        entries = audit.get_entries()
        assert len(entries) == 1
        assert entries[0].source_ip == "192.168.1.100"
        assert entries[0].success is False

    @pytest.mark.asyncio
    async def test_security_events_filtered_by_service(self) -> None:
        """Should filter security events by service."""
        audit = AuditTrail()

        await audit.log_security_event(
            event_type="cert_generated",
            service="opcua",
        )
        await audit.log_security_event(
            event_type="auth_success",
            service="modbus",
        )

        opcua_entries = audit.get_entries(service="opcua")
        assert len(opcua_entries) == 1
        assert opcua_entries[0].event_type == "cert_generated"


class TestNoSecretsInLogs:
    """Tests to verify secrets are not logged."""

    @pytest.mark.asyncio
    async def test_sensitive_details_not_in_log(self, caplog: pytest.LogCaptureFixture) -> None:
        """Should not log sensitive values in details."""
        audit = AuditTrail()

        await audit.log_security_event(
            event_type="auth_attempt",
            details={
                "username": "admin",
                "password": "supersecret",  # Should not appear in logs
                "api_key": "my-secret-key",  # Should not appear in logs
            },
        )

        # Check that log records don't contain sensitive values
        for record in caplog.records:
            log_message = record.getMessage()
            assert "supersecret" not in log_message
            assert "my-secret-key" not in log_message
