"""Unit tests for EIP (EtherNet/IP) connector driver.

Tests EIP address parsing and connector behavior for Allen-Bradley PLCs.
Follows TDD - these tests are written first, then implementation.

EIP Address Formats:
- Program:MainProgram.MyTag  - Program-scoped tag
- MyGlobalTag                - Controller-scoped tag
- MyArray[0]                 - Array element
- MyUDT.Member               - UDT member access
- MyTag{5}                   - Bit access (bit 5)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# Import will fail initially - that's expected for TDD
from mtp_gateway.adapters.southbound.base import ConnectorState
from mtp_gateway.adapters.southbound.eip.driver import (
    EIPConnector,
    parse_eip_address,
)
from mtp_gateway.config.schema import EIPConnectorConfig
from mtp_gateway.domain.model.tags import Quality

# =============================================================================
# EIP ADDRESS PARSING TESTS
# =============================================================================


class TestEIPAddressParsing:
    """Tests for EIP address string parsing."""

    # --- Simple tag names ---

    def test_parse_simple_tag(self) -> None:
        """MyTag → tag_name=MyTag, element=None, bit=None."""
        parsed = parse_eip_address("MyTag")
        assert parsed.tag_name == "MyTag"
        assert parsed.element is None
        assert parsed.bit is None

    def test_parse_simple_tag_with_underscore(self) -> None:
        """My_Tag_Name → tag_name=My_Tag_Name."""
        parsed = parse_eip_address("My_Tag_Name")
        assert parsed.tag_name == "My_Tag_Name"
        assert parsed.element is None
        assert parsed.bit is None

    def test_parse_simple_tag_with_numbers(self) -> None:
        """Tag123 → tag_name=Tag123."""
        parsed = parse_eip_address("Tag123")
        assert parsed.tag_name == "Tag123"

    # --- Program-scoped tags ---

    def test_parse_program_scoped_tag(self) -> None:
        """Program:MainProgram.MyTag → tag_name=Program:MainProgram.MyTag."""
        parsed = parse_eip_address("Program:MainProgram.MyTag")
        assert parsed.tag_name == "Program:MainProgram.MyTag"
        assert parsed.element is None
        assert parsed.bit is None

    def test_parse_program_scoped_tag_nested(self) -> None:
        """Program:MainProgram.Struct.Member → full path preserved."""
        parsed = parse_eip_address("Program:MainProgram.Struct.Member")
        assert parsed.tag_name == "Program:MainProgram.Struct.Member"

    # --- Array elements ---

    def test_parse_array_element(self) -> None:
        """MyArray[0] → tag_name=MyArray, element=0."""
        parsed = parse_eip_address("MyArray[0]")
        assert parsed.tag_name == "MyArray"
        assert parsed.element == 0
        assert parsed.bit is None

    def test_parse_array_element_high_index(self) -> None:
        """MyArray[100] → tag_name=MyArray, element=100."""
        parsed = parse_eip_address("MyArray[100]")
        assert parsed.tag_name == "MyArray"
        assert parsed.element == 100

    def test_parse_program_array_element(self) -> None:
        """Program:Main.Array[5] → tag_name=Program:Main.Array, element=5."""
        parsed = parse_eip_address("Program:Main.Array[5]")
        assert parsed.tag_name == "Program:Main.Array"
        assert parsed.element == 5

    # --- UDT member access ---

    def test_parse_udt_member(self) -> None:
        """MyUDT.Member → tag_name=MyUDT.Member."""
        parsed = parse_eip_address("MyUDT.Member")
        assert parsed.tag_name == "MyUDT.Member"
        assert parsed.element is None
        assert parsed.bit is None

    def test_parse_udt_nested_member(self) -> None:
        """MyUDT.Nested.DeepMember → tag_name=MyUDT.Nested.DeepMember."""
        parsed = parse_eip_address("MyUDT.Nested.DeepMember")
        assert parsed.tag_name == "MyUDT.Nested.DeepMember"

    def test_parse_udt_array_member(self) -> None:
        """MyUDT.ArrayMember[2] → tag_name=MyUDT.ArrayMember, element=2."""
        parsed = parse_eip_address("MyUDT.ArrayMember[2]")
        assert parsed.tag_name == "MyUDT.ArrayMember"
        assert parsed.element == 2

    # --- Bit access ---

    def test_parse_bit_access(self) -> None:
        """MyTag{5} → tag_name=MyTag, bit=5."""
        parsed = parse_eip_address("MyTag{5}")
        assert parsed.tag_name == "MyTag"
        assert parsed.element is None
        assert parsed.bit == 5

    def test_parse_bit_access_zero(self) -> None:
        """MyTag{0} → tag_name=MyTag, bit=0."""
        parsed = parse_eip_address("MyTag{0}")
        assert parsed.tag_name == "MyTag"
        assert parsed.bit == 0

    def test_parse_bit_access_high(self) -> None:
        """MyDINT{31} → tag_name=MyDINT, bit=31 (DINT has 32 bits)."""
        parsed = parse_eip_address("MyDINT{31}")
        assert parsed.tag_name == "MyDINT"
        assert parsed.bit == 31

    def test_parse_array_element_with_bit(self) -> None:
        """MyArray[0]{5} → tag_name=MyArray, element=0, bit=5."""
        parsed = parse_eip_address("MyArray[0]{5}")
        assert parsed.tag_name == "MyArray"
        assert parsed.element == 0
        assert parsed.bit == 5

    # --- Whitespace handling ---

    def test_parse_with_whitespace(self) -> None:
        """Address with leading/trailing whitespace."""
        parsed = parse_eip_address("  MyTag  ")
        assert parsed.tag_name == "MyTag"

    # --- Case preservation ---

    def test_parse_preserves_case(self) -> None:
        """EIP tag names are case-sensitive - preserve case."""
        parsed = parse_eip_address("MyMixedCaseTag")
        assert parsed.tag_name == "MyMixedCaseTag"

    # --- Invalid addresses ---

    def test_invalid_address_empty_raises(self) -> None:
        """Empty address should raise ValueError."""
        with pytest.raises(ValueError, match=r"[Ee]mpty|[Ii]nvalid"):
            parse_eip_address("")

    def test_invalid_address_whitespace_only_raises(self) -> None:
        """Whitespace-only address should raise ValueError."""
        with pytest.raises(ValueError, match=r"[Ee]mpty|[Ii]nvalid"):
            parse_eip_address("   ")

    def test_invalid_array_index_raises(self) -> None:
        """Non-numeric array index should raise ValueError."""
        with pytest.raises(ValueError, match=r"[Ii]nvalid"):
            parse_eip_address("MyArray[abc]")

    def test_invalid_bit_offset_raises(self) -> None:
        """Non-numeric bit offset should raise ValueError."""
        with pytest.raises(ValueError, match=r"[Ii]nvalid"):
            parse_eip_address("MyTag{x}")

    def test_unclosed_bracket_raises(self) -> None:
        """Unclosed array bracket should raise ValueError."""
        with pytest.raises(ValueError, match=r"[Ii]nvalid"):
            parse_eip_address("MyArray[0")

    def test_unclosed_brace_raises(self) -> None:
        """Unclosed bit brace should raise ValueError."""
        with pytest.raises(ValueError, match=r"[Ii]nvalid"):
            parse_eip_address("MyTag{5")


# =============================================================================
# EIP CONNECTOR TESTS (MOCKED)
# =============================================================================


class TestEIPConnectorMocked:
    """Tests for EIPConnector with mocked pycomm3 LogixDriver."""

    @pytest.fixture
    def eip_config(self) -> EIPConnectorConfig:
        """Create test EIP connector configuration."""
        return EIPConnectorConfig(
            name="test_eip",
            host="192.168.1.50",
            slot=0,
        )

    @pytest.fixture
    def mock_logix_driver(self) -> MagicMock:
        """Create mock pycomm3 LogixDriver."""
        mock_driver = MagicMock()
        mock_driver.__enter__ = MagicMock(return_value=mock_driver)
        mock_driver.__exit__ = MagicMock(return_value=False)
        return mock_driver

    async def test_connect_success(self, eip_config: EIPConnectorConfig) -> None:
        """Successful connection sets state to CONNECTED."""
        with (
            patch("mtp_gateway.adapters.southbound.eip.driver.LogixDriver") as mock_logix,
            patch("mtp_gateway.adapters.southbound.eip.driver.HAS_PYCOMM3", True),
        ):
            mock_driver = MagicMock()
            mock_driver.open.return_value = None
            mock_logix.return_value = mock_driver

            connector = EIPConnector(eip_config)
            await connector.connect()

            health = connector.health_status()
            assert health.state == ConnectorState.CONNECTED
            mock_logix.assert_called_once_with("192.168.1.50", slot=0)

    async def test_connect_failure_sets_error(self, eip_config: EIPConnectorConfig) -> None:
        """Connection failure sets ERROR state."""
        with (
            patch("mtp_gateway.adapters.southbound.eip.driver.LogixDriver") as mock_logix,
            patch("mtp_gateway.adapters.southbound.eip.driver.HAS_PYCOMM3", True),
        ):
            mock_driver = MagicMock()
            mock_driver.open.side_effect = Exception("Connection refused")
            mock_logix.return_value = mock_driver

            connector = EIPConnector(eip_config)

            with pytest.raises(ConnectionError):
                await connector.connect()

            health = connector.health_status()
            assert health.state == ConnectorState.ERROR

    async def test_read_tags_returns_tag_values(self, eip_config: EIPConnectorConfig) -> None:
        """Reading tags returns dict of TagValue objects."""
        with (
            patch("mtp_gateway.adapters.southbound.eip.driver.LogixDriver") as mock_logix,
            patch("mtp_gateway.adapters.southbound.eip.driver.HAS_PYCOMM3", True),
        ):
            mock_driver = MagicMock()
            mock_driver.open.return_value = None

            # pycomm3 read() returns Tag objects with .value and .error attributes
            mock_tag = MagicMock()
            mock_tag.value = 25.5
            mock_tag.error = None
            mock_driver.read.return_value = mock_tag

            mock_logix.return_value = mock_driver

            connector = EIPConnector(eip_config)
            await connector.connect()

            result = await connector.read_tags(["MyFloatTag"])

            assert "MyFloatTag" in result
            tag_value = result["MyFloatTag"]
            assert tag_value.quality == Quality.GOOD
            assert abs(tag_value.value - 25.5) < 0.0001

    async def test_read_multiple_tags(self, eip_config: EIPConnectorConfig) -> None:
        """Reading multiple tags returns all values via batch read."""
        with (
            patch("mtp_gateway.adapters.southbound.eip.driver.LogixDriver") as mock_logix,
            patch("mtp_gateway.adapters.southbound.eip.driver.HAS_PYCOMM3", True),
        ):
            mock_driver = MagicMock()
            mock_driver.open.return_value = None

            # pycomm3 batch read returns list of Tag objects
            mock_tag1 = MagicMock()
            mock_tag1.tag = "Tag1"
            mock_tag1.value = 10.0
            mock_tag1.error = None

            mock_tag2 = MagicMock()
            mock_tag2.tag = "Tag2"
            mock_tag2.value = 20.0
            mock_tag2.error = None

            mock_driver.read.return_value = [mock_tag1, mock_tag2]
            mock_logix.return_value = mock_driver

            connector = EIPConnector(eip_config)
            await connector.connect()

            result = await connector.read_tags(["Tag1", "Tag2"])

            assert len(result) == 2
            assert "Tag1" in result
            assert "Tag2" in result
            assert abs(result["Tag1"].value - 10.0) < 0.0001
            assert abs(result["Tag2"].value - 20.0) < 0.0001

    async def test_read_failure_returns_bad_quality(self, eip_config: EIPConnectorConfig) -> None:
        """Read errors return bad quality."""
        with (
            patch("mtp_gateway.adapters.southbound.eip.driver.LogixDriver") as mock_logix,
            patch("mtp_gateway.adapters.southbound.eip.driver.HAS_PYCOMM3", True),
        ):
            mock_driver = MagicMock()
            mock_driver.open.return_value = None
            mock_driver.read.side_effect = Exception("Read timeout")
            mock_logix.return_value = mock_driver

            connector = EIPConnector(eip_config)
            await connector.connect()

            result = await connector.read_tags(["MyTag"])

            assert "MyTag" in result
            assert result["MyTag"].quality.is_bad()

    async def test_read_tag_with_error_returns_bad_quality(
        self, eip_config: EIPConnectorConfig
    ) -> None:
        """Tag read with error attribute set returns bad quality."""
        with (
            patch("mtp_gateway.adapters.southbound.eip.driver.LogixDriver") as mock_logix,
            patch("mtp_gateway.adapters.southbound.eip.driver.HAS_PYCOMM3", True),
        ):
            mock_driver = MagicMock()
            mock_driver.open.return_value = None

            # Tag with error
            mock_tag = MagicMock()
            mock_tag.tag = "BadTag"
            mock_tag.value = None
            mock_tag.error = "Path segment error"

            mock_driver.read.return_value = mock_tag
            mock_logix.return_value = mock_driver

            connector = EIPConnector(eip_config)
            await connector.connect()

            result = await connector.read_tags(["BadTag"])

            assert "BadTag" in result
            # Tag with error should have BAD_CONFIG_ERROR quality
            assert result["BadTag"].quality == Quality.BAD_CONFIG_ERROR

    async def test_read_program_scoped_tag(self, eip_config: EIPConnectorConfig) -> None:
        """Read program-scoped tag."""
        with (
            patch("mtp_gateway.adapters.southbound.eip.driver.LogixDriver") as mock_logix,
            patch("mtp_gateway.adapters.southbound.eip.driver.HAS_PYCOMM3", True),
        ):
            mock_driver = MagicMock()
            mock_driver.open.return_value = None

            mock_tag = MagicMock()
            mock_tag.value = 42
            mock_tag.error = None
            mock_driver.read.return_value = mock_tag

            mock_logix.return_value = mock_driver

            connector = EIPConnector(eip_config)
            await connector.connect()

            result = await connector.read_tags(["Program:MainProgram.Counter"])

            assert "Program:MainProgram.Counter" in result
            assert result["Program:MainProgram.Counter"].value == 42

    async def test_read_array_element(self, eip_config: EIPConnectorConfig) -> None:
        """Read array element."""
        with (
            patch("mtp_gateway.adapters.southbound.eip.driver.LogixDriver") as mock_logix,
            patch("mtp_gateway.adapters.southbound.eip.driver.HAS_PYCOMM3", True),
        ):
            mock_driver = MagicMock()
            mock_driver.open.return_value = None

            mock_tag = MagicMock()
            mock_tag.value = 123
            mock_tag.error = None
            mock_driver.read.return_value = mock_tag

            mock_logix.return_value = mock_driver

            connector = EIPConnector(eip_config)
            await connector.connect()

            result = await connector.read_tags(["MyArray[5]"])

            assert "MyArray[5]" in result
            assert result["MyArray[5]"].value == 123

    async def test_write_tag_success(self, eip_config: EIPConnectorConfig) -> None:
        """Write returns True on success."""
        with (
            patch("mtp_gateway.adapters.southbound.eip.driver.LogixDriver") as mock_logix,
            patch("mtp_gateway.adapters.southbound.eip.driver.HAS_PYCOMM3", True),
        ):
            mock_driver = MagicMock()
            mock_driver.open.return_value = None

            # pycomm3 write returns Tag object
            mock_result = MagicMock()
            mock_result.error = None
            mock_driver.write.return_value = mock_result

            mock_logix.return_value = mock_driver

            connector = EIPConnector(eip_config)
            await connector.connect()

            result = await connector.write_tag("MyFloatTag", 42.5)

            assert result is True
            mock_driver.write.assert_called_once()

    async def test_write_tag_failure(self, eip_config: EIPConnectorConfig) -> None:
        """Write returns False on failure."""
        with (
            patch("mtp_gateway.adapters.southbound.eip.driver.LogixDriver") as mock_logix,
            patch("mtp_gateway.adapters.southbound.eip.driver.HAS_PYCOMM3", True),
        ):
            mock_driver = MagicMock()
            mock_driver.open.return_value = None
            mock_driver.write.side_effect = Exception("Write error")
            mock_logix.return_value = mock_driver

            connector = EIPConnector(eip_config)
            await connector.connect()

            result = await connector.write_tag("MyTag", 100)

            assert result is False

    async def test_write_with_error_response(self, eip_config: EIPConnectorConfig) -> None:
        """Write with error in response returns False."""
        with (
            patch("mtp_gateway.adapters.southbound.eip.driver.LogixDriver") as mock_logix,
            patch("mtp_gateway.adapters.southbound.eip.driver.HAS_PYCOMM3", True),
        ):
            mock_driver = MagicMock()
            mock_driver.open.return_value = None

            mock_result = MagicMock()
            mock_result.error = "Access denied"
            mock_driver.write.return_value = mock_result

            mock_logix.return_value = mock_driver

            connector = EIPConnector(eip_config)
            await connector.connect()

            result = await connector.write_tag("ReadOnlyTag", 50)

            assert result is False

    async def test_write_bool_tag(self, eip_config: EIPConnectorConfig) -> None:
        """Write boolean value to tag."""
        with (
            patch("mtp_gateway.adapters.southbound.eip.driver.LogixDriver") as mock_logix,
            patch("mtp_gateway.adapters.southbound.eip.driver.HAS_PYCOMM3", True),
        ):
            mock_driver = MagicMock()
            mock_driver.open.return_value = None

            mock_result = MagicMock()
            mock_result.error = None
            mock_driver.write.return_value = mock_result

            mock_logix.return_value = mock_driver

            connector = EIPConnector(eip_config)
            await connector.connect()

            result = await connector.write_tag("MyBoolTag", True)

            assert result is True
            # Verify the value passed to write
            call_args = mock_driver.write.call_args
            assert call_args is not None

    async def test_write_array_element(self, eip_config: EIPConnectorConfig) -> None:
        """Write to array element."""
        with (
            patch("mtp_gateway.adapters.southbound.eip.driver.LogixDriver") as mock_logix,
            patch("mtp_gateway.adapters.southbound.eip.driver.HAS_PYCOMM3", True),
        ):
            mock_driver = MagicMock()
            mock_driver.open.return_value = None

            mock_result = MagicMock()
            mock_result.error = None
            mock_driver.write.return_value = mock_result

            mock_logix.return_value = mock_driver

            connector = EIPConnector(eip_config)
            await connector.connect()

            result = await connector.write_tag("MyArray[3]", 999)

            assert result is True

    async def test_disconnect_graceful(self, eip_config: EIPConnectorConfig) -> None:
        """Disconnect closes driver cleanly."""
        with (
            patch("mtp_gateway.adapters.southbound.eip.driver.LogixDriver") as mock_logix,
            patch("mtp_gateway.adapters.southbound.eip.driver.HAS_PYCOMM3", True),
        ):
            mock_driver = MagicMock()
            mock_driver.open.return_value = None
            mock_logix.return_value = mock_driver

            connector = EIPConnector(eip_config)
            await connector.connect()
            await connector.disconnect()

            mock_driver.close.assert_called_once()
            health = connector.health_status()
            assert health.state == ConnectorState.STOPPED

    async def test_read_without_connect_fails(self, eip_config: EIPConnectorConfig) -> None:
        """Reading without connecting returns bad quality."""
        with (
            patch("mtp_gateway.adapters.southbound.eip.driver.LogixDriver"),
            patch("mtp_gateway.adapters.southbound.eip.driver.HAS_PYCOMM3", True),
        ):
            connector = EIPConnector(eip_config)

            result = await connector.read_tags(["MyTag"])

            assert "MyTag" in result
            assert result["MyTag"].quality.is_bad()


# =============================================================================
# EIP CONNECTOR IMPORT ERROR HANDLING
# =============================================================================


class TestEIPConnectorImportHandling:
    """Tests for pycomm3 import error handling."""

    def test_missing_pycomm3_raises_import_error(self) -> None:
        """Creating connector without pycomm3 raises ImportError."""
        with (
            patch("mtp_gateway.adapters.southbound.eip.driver.HAS_PYCOMM3", False),
            patch("mtp_gateway.adapters.southbound.eip.driver.LogixDriver", None),
        ):
            config = EIPConnectorConfig(
                name="test_eip",
                host="192.168.1.50",
                slot=0,
            )

            with pytest.raises(ImportError, match="pycomm3"):
                EIPConnector(config)
