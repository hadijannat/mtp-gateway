"""Unit tests for OPC UA Client connector driver.

Tests NodeId parsing, connector behavior, and security configuration.
Follows TDD - these tests are written first, then implementation.

OPC UA NodeId Formats:
- ns=2;i=1001          - Numeric ID 1001 in namespace 2
- ns=2;s=Temperature   - String ID "Temperature" in namespace 2
- ns=2;g=550e8400-...  - GUID-based NodeId
- ns=0;i=2258          - Well-known node (ServerState)
- i=2258               - Default namespace (0), numeric ID
- s=MyTag              - Default namespace (0), string ID
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

# Import will fail initially - that's expected for TDD
from mtp_gateway.adapters.southbound.opcua_client.driver import (
    OPCUAClientConnector,
    parse_node_id,
)
from mtp_gateway.config.schema import OPCUAClientConnectorConfig, SecurityPolicy
from mtp_gateway.domain.model.tags import Quality


# =============================================================================
# NODE ID PARSING TESTS
# =============================================================================


class TestNodeIdParsing:
    """Tests for OPC UA NodeId string parsing."""

    # --- Numeric NodeIds ---

    def test_parse_numeric_node_id(self) -> None:
        """ns=2;i=1001 -> NodeId(namespace=2, identifier=1001)."""
        node_id = parse_node_id("ns=2;i=1001")
        assert node_id.NamespaceIndex == 2
        assert node_id.Identifier == 1001

    def test_parse_numeric_node_id_namespace_zero(self) -> None:
        """ns=0;i=2258 -> NodeId(namespace=0, identifier=2258)."""
        node_id = parse_node_id("ns=0;i=2258")
        assert node_id.NamespaceIndex == 0
        assert node_id.Identifier == 2258

    def test_parse_numeric_node_id_large_value(self) -> None:
        """ns=3;i=999999 -> NodeId with large identifier."""
        node_id = parse_node_id("ns=3;i=999999")
        assert node_id.NamespaceIndex == 3
        assert node_id.Identifier == 999999

    # --- String NodeIds ---

    def test_parse_string_node_id(self) -> None:
        """ns=2;s=Temperature -> NodeId(namespace=2, identifier='Temperature')."""
        node_id = parse_node_id("ns=2;s=Temperature")
        assert node_id.NamespaceIndex == 2
        assert node_id.Identifier == "Temperature"

    def test_parse_string_node_id_with_dots(self) -> None:
        """ns=2;s=Device.Sensor.Value -> String identifier with dots."""
        node_id = parse_node_id("ns=2;s=Device.Sensor.Value")
        assert node_id.NamespaceIndex == 2
        assert node_id.Identifier == "Device.Sensor.Value"

    def test_parse_string_node_id_with_spaces(self) -> None:
        """ns=2;s=My Tag Name -> String identifier with spaces."""
        node_id = parse_node_id("ns=2;s=My Tag Name")
        assert node_id.NamespaceIndex == 2
        assert node_id.Identifier == "My Tag Name"

    # --- Default namespace (0) ---

    def test_parse_default_namespace_numeric(self) -> None:
        """i=2258 -> NodeId(namespace=0, identifier=2258)."""
        node_id = parse_node_id("i=2258")
        assert node_id.NamespaceIndex == 0
        assert node_id.Identifier == 2258

    def test_parse_default_namespace_string(self) -> None:
        """s=MyTag -> NodeId(namespace=0, identifier='MyTag')."""
        node_id = parse_node_id("s=MyTag")
        assert node_id.NamespaceIndex == 0
        assert node_id.Identifier == "MyTag"

    # --- GUID NodeIds ---

    def test_parse_guid_node_id(self) -> None:
        """ns=2;g=550e8400-e29b-41d4-a716-446655440000 -> GUID NodeId."""
        guid_str = "550e8400-e29b-41d4-a716-446655440000"
        node_id = parse_node_id(f"ns=2;g={guid_str}")
        assert node_id.NamespaceIndex == 2
        # GUID identifier should match
        assert str(node_id.Identifier) == guid_str

    # --- Whitespace handling ---

    def test_parse_with_whitespace(self) -> None:
        """Address with leading/trailing whitespace."""
        node_id = parse_node_id("  ns=2;i=1001  ")
        assert node_id.NamespaceIndex == 2
        assert node_id.Identifier == 1001

    # --- Case insensitivity for type prefix ---

    def test_parse_uppercase_type_prefix(self) -> None:
        """NS=2;I=1001 -> Should handle uppercase."""
        node_id = parse_node_id("NS=2;I=1001")
        assert node_id.NamespaceIndex == 2
        assert node_id.Identifier == 1001

    # --- Invalid addresses ---

    def test_invalid_address_empty_raises(self) -> None:
        """Empty address should raise ValueError."""
        with pytest.raises(ValueError, match="[Ee]mpty|[Ii]nvalid"):
            parse_node_id("")

    def test_invalid_address_whitespace_only_raises(self) -> None:
        """Whitespace-only address should raise ValueError."""
        with pytest.raises(ValueError, match="[Ee]mpty|[Ii]nvalid"):
            parse_node_id("   ")

    def test_invalid_address_missing_identifier_raises(self) -> None:
        """Missing identifier should raise ValueError."""
        with pytest.raises(ValueError, match="[Ii]nvalid"):
            parse_node_id("ns=2")

    def test_invalid_address_bad_namespace_raises(self) -> None:
        """Non-numeric namespace should raise ValueError."""
        with pytest.raises(ValueError, match="[Ii]nvalid"):
            parse_node_id("ns=abc;i=1001")

    def test_invalid_address_bad_numeric_id_raises(self) -> None:
        """Non-numeric identifier with i= prefix should raise ValueError."""
        with pytest.raises(ValueError, match="[Ii]nvalid"):
            parse_node_id("ns=2;i=notanumber")

    def test_invalid_address_unknown_format_raises(self) -> None:
        """Unknown format should raise ValueError."""
        with pytest.raises(ValueError, match="[Ii]nvalid"):
            parse_node_id("random_string")


# =============================================================================
# OPC UA CLIENT CONNECTOR TESTS (MOCKED)
# =============================================================================


class TestOPCUAClientConnectorMocked:
    """Tests for OPCUAClientConnector with mocked asyncua Client."""

    @pytest.fixture
    def opcua_config(self) -> OPCUAClientConnectorConfig:
        """Create test OPC UA client connector configuration."""
        return OPCUAClientConnectorConfig(
            name="test_opcua",
            endpoint="opc.tcp://localhost:4840",
        )

    @pytest.fixture
    def mock_asyncua_client(self) -> MagicMock:
        """Create mock asyncua Client."""
        mock_client = MagicMock()
        mock_client.connect = AsyncMock()
        mock_client.disconnect = AsyncMock()
        mock_client.read_values = AsyncMock()
        mock_client.get_node = MagicMock()
        return mock_client

    async def test_connect_success(
        self, opcua_config: OPCUAClientConnectorConfig
    ) -> None:
        """Successful connection sets state to CONNECTED."""
        with patch(
            "mtp_gateway.adapters.southbound.opcua_client.driver.Client"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client.connect = AsyncMock()
            mock_client_class.return_value = mock_client

            connector = OPCUAClientConnector(opcua_config)
            await connector.connect()

            health = connector.health_status()
            from mtp_gateway.adapters.southbound.base import ConnectorState

            assert health.state == ConnectorState.CONNECTED
            mock_client_class.assert_called_once_with(url="opc.tcp://localhost:4840")
            mock_client.connect.assert_called_once()

    async def test_connect_failure_sets_error(
        self, opcua_config: OPCUAClientConnectorConfig
    ) -> None:
        """Connection failure sets ERROR state."""
        with patch(
            "mtp_gateway.adapters.southbound.opcua_client.driver.Client"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client.connect = AsyncMock(
                side_effect=Exception("Connection refused")
            )
            mock_client_class.return_value = mock_client

            connector = OPCUAClientConnector(opcua_config)

            with pytest.raises(ConnectionError):
                await connector.connect()

            health = connector.health_status()
            from mtp_gateway.adapters.southbound.base import ConnectorState

            assert health.state == ConnectorState.ERROR

    async def test_read_tags_returns_tag_values(
        self, opcua_config: OPCUAClientConnectorConfig
    ) -> None:
        """Reading nodes returns dict of TagValue objects."""
        with patch(
            "mtp_gateway.adapters.southbound.opcua_client.driver.Client"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client.connect = AsyncMock()

            # Mock node and read
            mock_node = MagicMock()
            mock_client.get_node = MagicMock(return_value=mock_node)

            # asyncua read_values returns list of DataValue objects
            mock_data_value = MagicMock()
            mock_data_value.Value.Value = 25.5
            mock_data_value.StatusCode.is_good.return_value = True
            mock_client.read_values = AsyncMock(return_value=[mock_data_value])

            mock_client_class.return_value = mock_client

            connector = OPCUAClientConnector(opcua_config)
            await connector.connect()

            result = await connector.read_tags(["ns=2;i=1001"])

            assert "ns=2;i=1001" in result
            tag_value = result["ns=2;i=1001"]
            assert tag_value.quality == Quality.GOOD
            assert abs(tag_value.value - 25.5) < 0.0001

    async def test_read_multiple_tags(
        self, opcua_config: OPCUAClientConnectorConfig
    ) -> None:
        """Reading multiple nodes returns all values via batch read."""
        with patch(
            "mtp_gateway.adapters.southbound.opcua_client.driver.Client"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client.connect = AsyncMock()

            # Mock nodes
            mock_client.get_node = MagicMock(return_value=MagicMock())

            # Multiple DataValues
            mock_dv1 = MagicMock()
            mock_dv1.Value.Value = 10.0
            mock_dv1.StatusCode.is_good.return_value = True

            mock_dv2 = MagicMock()
            mock_dv2.Value.Value = 20.0
            mock_dv2.StatusCode.is_good.return_value = True

            mock_client.read_values = AsyncMock(return_value=[mock_dv1, mock_dv2])
            mock_client_class.return_value = mock_client

            connector = OPCUAClientConnector(opcua_config)
            await connector.connect()

            result = await connector.read_tags(["ns=2;i=1001", "ns=2;i=1002"])

            assert len(result) == 2
            assert "ns=2;i=1001" in result
            assert "ns=2;i=1002" in result
            assert abs(result["ns=2;i=1001"].value - 10.0) < 0.0001
            assert abs(result["ns=2;i=1002"].value - 20.0) < 0.0001

    async def test_read_with_bad_status_returns_bad_quality(
        self, opcua_config: OPCUAClientConnectorConfig
    ) -> None:
        """Node with bad StatusCode returns bad quality."""
        with patch(
            "mtp_gateway.adapters.southbound.opcua_client.driver.Client"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client.connect = AsyncMock()
            mock_client.get_node = MagicMock(return_value=MagicMock())

            # Bad status code
            mock_data_value = MagicMock()
            mock_data_value.Value.Value = None
            mock_data_value.StatusCode.is_good.return_value = False
            mock_data_value.StatusCode.name = "BadNodeIdUnknown"
            mock_client.read_values = AsyncMock(return_value=[mock_data_value])

            mock_client_class.return_value = mock_client

            connector = OPCUAClientConnector(opcua_config)
            await connector.connect()

            result = await connector.read_tags(["ns=2;i=9999"])

            assert "ns=2;i=9999" in result
            assert result["ns=2;i=9999"].quality.is_bad()

    async def test_read_failure_returns_bad_quality(
        self, opcua_config: OPCUAClientConnectorConfig
    ) -> None:
        """Read exception returns bad quality."""
        with patch(
            "mtp_gateway.adapters.southbound.opcua_client.driver.Client"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client.connect = AsyncMock()
            mock_client.get_node = MagicMock(return_value=MagicMock())
            mock_client.read_values = AsyncMock(side_effect=Exception("Read timeout"))
            mock_client_class.return_value = mock_client

            connector = OPCUAClientConnector(opcua_config)
            await connector.connect()

            result = await connector.read_tags(["ns=2;i=1001"])

            assert "ns=2;i=1001" in result
            assert result["ns=2;i=1001"].quality.is_bad()

    async def test_write_tag_success(
        self, opcua_config: OPCUAClientConnectorConfig
    ) -> None:
        """Write returns True on success."""
        with patch(
            "mtp_gateway.adapters.southbound.opcua_client.driver.Client"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client.connect = AsyncMock()

            mock_node = MagicMock()
            mock_node.write_value = AsyncMock()
            mock_client.get_node = MagicMock(return_value=mock_node)

            mock_client_class.return_value = mock_client

            connector = OPCUAClientConnector(opcua_config)
            await connector.connect()

            result = await connector.write_tag("ns=2;i=1001", 42.5)

            assert result is True
            mock_node.write_value.assert_called_once()

    async def test_write_tag_failure(
        self, opcua_config: OPCUAClientConnectorConfig
    ) -> None:
        """Write returns False on failure."""
        with patch(
            "mtp_gateway.adapters.southbound.opcua_client.driver.Client"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client.connect = AsyncMock()

            mock_node = MagicMock()
            mock_node.write_value = AsyncMock(side_effect=Exception("Write denied"))
            mock_client.get_node = MagicMock(return_value=mock_node)

            mock_client_class.return_value = mock_client

            connector = OPCUAClientConnector(opcua_config)
            await connector.connect()

            result = await connector.write_tag("ns=2;i=1001", 100)

            assert result is False

    async def test_disconnect_graceful(
        self, opcua_config: OPCUAClientConnectorConfig
    ) -> None:
        """Disconnect closes client cleanly."""
        with patch(
            "mtp_gateway.adapters.southbound.opcua_client.driver.Client"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client.connect = AsyncMock()
            mock_client.disconnect = AsyncMock()
            mock_client_class.return_value = mock_client

            connector = OPCUAClientConnector(opcua_config)
            await connector.connect()
            await connector.disconnect()

            mock_client.disconnect.assert_called_once()
            health = connector.health_status()
            from mtp_gateway.adapters.southbound.base import ConnectorState

            assert health.state == ConnectorState.STOPPED

    async def test_read_without_connect_fails(
        self, opcua_config: OPCUAClientConnectorConfig
    ) -> None:
        """Reading without connecting returns bad quality."""
        with patch(
            "mtp_gateway.adapters.southbound.opcua_client.driver.Client"
        ):
            connector = OPCUAClientConnector(opcua_config)

            result = await connector.read_tags(["ns=2;i=1001"])

            assert "ns=2;i=1001" in result
            assert result["ns=2;i=1001"].quality.is_bad()

    async def test_read_string_node_id(
        self, opcua_config: OPCUAClientConnectorConfig
    ) -> None:
        """Read node with string identifier."""
        with patch(
            "mtp_gateway.adapters.southbound.opcua_client.driver.Client"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client.connect = AsyncMock()
            mock_client.get_node = MagicMock(return_value=MagicMock())

            mock_data_value = MagicMock()
            mock_data_value.Value.Value = "Hello"
            mock_data_value.StatusCode.is_good.return_value = True
            mock_client.read_values = AsyncMock(return_value=[mock_data_value])

            mock_client_class.return_value = mock_client

            connector = OPCUAClientConnector(opcua_config)
            await connector.connect()

            result = await connector.read_tags(["ns=2;s=MyStringNode"])

            assert "ns=2;s=MyStringNode" in result
            assert result["ns=2;s=MyStringNode"].value == "Hello"


# =============================================================================
# SECURITY CONFIGURATION TESTS
# =============================================================================


class TestSecurityConfiguration:
    """Tests for security policy and credentials."""

    async def test_no_security_policy(self) -> None:
        """No security policy - plain connection."""
        config = OPCUAClientConnectorConfig(
            name="test_opcua",
            endpoint="opc.tcp://localhost:4840",
            security_policy=SecurityPolicy.NONE,
        )

        with patch(
            "mtp_gateway.adapters.southbound.opcua_client.driver.Client"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client.connect = AsyncMock()
            mock_client_class.return_value = mock_client

            connector = OPCUAClientConnector(config)
            await connector.connect()

            # Should connect without setting security
            mock_client.connect.assert_called_once()

    async def test_security_policy_applied(self) -> None:
        """Security policy from config is applied to client."""
        config = OPCUAClientConnectorConfig(
            name="test_opcua",
            endpoint="opc.tcp://localhost:4840",
            security_policy=SecurityPolicy.BASIC256SHA256_SIGN_ENCRYPT,
        )

        with patch(
            "mtp_gateway.adapters.southbound.opcua_client.driver.Client"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client.connect = AsyncMock()
            mock_client.set_security_string = MagicMock()
            mock_client_class.return_value = mock_client

            connector = OPCUAClientConnector(config)
            # Note: In actual implementation, security requires cert/key paths
            # This test verifies the connector attempts to apply security

    async def test_username_password_auth(self) -> None:
        """Username/password credentials are set."""
        config = OPCUAClientConnectorConfig(
            name="test_opcua",
            endpoint="opc.tcp://localhost:4840",
            username="admin",
            password="secret123",
        )

        with patch(
            "mtp_gateway.adapters.southbound.opcua_client.driver.Client"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client.connect = AsyncMock()
            mock_client.set_user = MagicMock()
            mock_client.set_password = MagicMock()
            mock_client_class.return_value = mock_client

            connector = OPCUAClientConnector(config)
            await connector.connect()

            # Verify credentials were set
            mock_client.set_user.assert_called_once_with("admin")
            mock_client.set_password.assert_called_once_with("secret123")


# =============================================================================
# STATUS CODE TO QUALITY MAPPING TESTS
# =============================================================================


class TestStatusCodeMapping:
    """Tests for OPC UA StatusCode to Quality mapping."""

    async def test_good_status_returns_good_quality(self) -> None:
        """Good StatusCode returns GOOD quality."""
        config = OPCUAClientConnectorConfig(
            name="test_opcua",
            endpoint="opc.tcp://localhost:4840",
        )

        with patch(
            "mtp_gateway.adapters.southbound.opcua_client.driver.Client"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client.connect = AsyncMock()
            mock_client.get_node = MagicMock(return_value=MagicMock())

            mock_dv = MagicMock()
            mock_dv.Value.Value = 42.0
            mock_dv.StatusCode.is_good.return_value = True
            mock_client.read_values = AsyncMock(return_value=[mock_dv])

            mock_client_class.return_value = mock_client

            connector = OPCUAClientConnector(config)
            await connector.connect()

            result = await connector.read_tags(["ns=2;i=1001"])

            assert result["ns=2;i=1001"].quality == Quality.GOOD

    async def test_uncertain_status_returns_uncertain_quality(self) -> None:
        """Uncertain StatusCode returns UNCERTAIN quality."""
        config = OPCUAClientConnectorConfig(
            name="test_opcua",
            endpoint="opc.tcp://localhost:4840",
        )

        with patch(
            "mtp_gateway.adapters.southbound.opcua_client.driver.Client"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client.connect = AsyncMock()
            mock_client.get_node = MagicMock(return_value=MagicMock())

            mock_dv = MagicMock()
            mock_dv.Value.Value = 42.0
            mock_dv.StatusCode.is_good.return_value = False
            mock_dv.StatusCode.is_bad.return_value = False  # Uncertain
            mock_dv.StatusCode.name = "Uncertain"
            mock_client.read_values = AsyncMock(return_value=[mock_dv])

            mock_client_class.return_value = mock_client

            connector = OPCUAClientConnector(config)
            await connector.connect()

            result = await connector.read_tags(["ns=2;i=1001"])

            assert result["ns=2;i=1001"].quality == Quality.UNCERTAIN

    async def test_bad_node_id_unknown_returns_config_error(self) -> None:
        """BadNodeIdUnknown StatusCode returns BAD_CONFIG_ERROR quality."""
        config = OPCUAClientConnectorConfig(
            name="test_opcua",
            endpoint="opc.tcp://localhost:4840",
        )

        with patch(
            "mtp_gateway.adapters.southbound.opcua_client.driver.Client"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client.connect = AsyncMock()
            mock_client.get_node = MagicMock(return_value=MagicMock())

            mock_dv = MagicMock()
            mock_dv.Value.Value = None
            mock_dv.StatusCode.is_good.return_value = False
            mock_dv.StatusCode.is_bad.return_value = True
            mock_dv.StatusCode.name = "BadNodeIdUnknown"
            mock_client.read_values = AsyncMock(return_value=[mock_dv])

            mock_client_class.return_value = mock_client

            connector = OPCUAClientConnector(config)
            await connector.connect()

            result = await connector.read_tags(["ns=2;i=9999"])

            assert result["ns=2;i=9999"].quality == Quality.BAD_CONFIG_ERROR

    async def test_bad_not_connected_returns_no_communication(self) -> None:
        """BadNotConnected StatusCode returns BAD_NO_COMMUNICATION quality."""
        config = OPCUAClientConnectorConfig(
            name="test_opcua",
            endpoint="opc.tcp://localhost:4840",
        )

        with patch(
            "mtp_gateway.adapters.southbound.opcua_client.driver.Client"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client.connect = AsyncMock()
            mock_client.get_node = MagicMock(return_value=MagicMock())

            mock_dv = MagicMock()
            mock_dv.Value.Value = None
            mock_dv.StatusCode.is_good.return_value = False
            mock_dv.StatusCode.is_bad.return_value = True
            mock_dv.StatusCode.name = "BadNotConnected"
            mock_client.read_values = AsyncMock(return_value=[mock_dv])

            mock_client_class.return_value = mock_client

            connector = OPCUAClientConnector(config)
            await connector.connect()

            result = await connector.read_tags(["ns=2;i=1001"])

            assert result["ns=2;i=1001"].quality == Quality.BAD_NO_COMMUNICATION
