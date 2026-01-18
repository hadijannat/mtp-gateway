"""Unit tests for S7 connector driver.

Tests S7 address parsing, data type encoding/decoding, and connector behavior.
Follows TDD - these tests are written first, then implementation.
"""

from __future__ import annotations

import struct
from unittest.mock import MagicMock, patch

import pytest

# Import will fail initially - that's expected for TDD
from mtp_gateway.adapters.southbound.base import ConnectorState
from mtp_gateway.adapters.southbound.s7.driver import (
    S7AreaType,
    S7Connector,
    decode_s7_value,
    encode_s7_value,
    parse_s7_address,
)
from mtp_gateway.config.schema import S7ConnectorConfig
from mtp_gateway.domain.model.tags import Quality

# =============================================================================
# S7 ADDRESS PARSING TESTS
# =============================================================================


class TestS7AddressParsing:
    """Tests for S7 address string parsing."""

    # --- Data Block addresses ---

    def test_parse_db_double_word(self) -> None:
        """DB100.DBD0 → area=DB, db=100, offset=0, size=4 (float/dint)."""
        parsed = parse_s7_address("DB100.DBD0")
        assert parsed.area == S7AreaType.DB
        assert parsed.db_number == 100
        assert parsed.offset == 0
        assert parsed.size == 4
        assert parsed.bit_offset is None
        assert parsed.data_type == "DBD"

    def test_parse_db_double_word_at_offset(self) -> None:
        """DB50.DBD12 → area=DB, db=50, offset=12, size=4."""
        parsed = parse_s7_address("DB50.DBD12")
        assert parsed.area == S7AreaType.DB
        assert parsed.db_number == 50
        assert parsed.offset == 12
        assert parsed.size == 4

    def test_parse_db_word(self) -> None:
        """DB100.DBW10 → area=DB, db=100, offset=10, size=2 (int16)."""
        parsed = parse_s7_address("DB100.DBW10")
        assert parsed.area == S7AreaType.DB
        assert parsed.db_number == 100
        assert parsed.offset == 10
        assert parsed.size == 2
        assert parsed.data_type == "DBW"

    def test_parse_db_byte(self) -> None:
        """DB100.DBB20 → area=DB, db=100, offset=20, size=1 (byte/uint8)."""
        parsed = parse_s7_address("DB100.DBB20")
        assert parsed.area == S7AreaType.DB
        assert parsed.db_number == 100
        assert parsed.offset == 20
        assert parsed.size == 1
        assert parsed.data_type == "DBB"

    def test_parse_db_bit(self) -> None:
        """DB100.DBX30.0 → area=DB, db=100, offset=30, bit=0."""
        parsed = parse_s7_address("DB100.DBX30.0")
        assert parsed.area == S7AreaType.DB
        assert parsed.db_number == 100
        assert parsed.offset == 30
        assert parsed.bit_offset == 0
        assert parsed.size == 1
        assert parsed.data_type == "DBX"

    def test_parse_db_bit_high(self) -> None:
        """DB200.DBX5.7 → area=DB, db=200, offset=5, bit=7."""
        parsed = parse_s7_address("DB200.DBX5.7")
        assert parsed.area == S7AreaType.DB
        assert parsed.db_number == 200
        assert parsed.offset == 5
        assert parsed.bit_offset == 7

    # --- Memory (Marker) addresses ---

    def test_parse_memory_bit(self) -> None:
        """M0.0 → area=M, offset=0, bit=0."""
        parsed = parse_s7_address("M0.0")
        assert parsed.area == S7AreaType.M
        assert parsed.db_number is None
        assert parsed.offset == 0
        assert parsed.bit_offset == 0
        assert parsed.size == 1

    def test_parse_memory_bit_high_offset(self) -> None:
        """M10.5 → area=M, offset=10, bit=5."""
        parsed = parse_s7_address("M10.5")
        assert parsed.area == S7AreaType.M
        assert parsed.offset == 10
        assert parsed.bit_offset == 5

    def test_parse_memory_byte(self) -> None:
        """MB100 → area=M, offset=100, size=1."""
        parsed = parse_s7_address("MB100")
        assert parsed.area == S7AreaType.M
        assert parsed.offset == 100
        assert parsed.size == 1
        assert parsed.bit_offset is None

    def test_parse_memory_word(self) -> None:
        """MW100 → area=M, offset=100, size=2."""
        parsed = parse_s7_address("MW100")
        assert parsed.area == S7AreaType.M
        assert parsed.offset == 100
        assert parsed.size == 2

    def test_parse_memory_double_word(self) -> None:
        """MD100 → area=M, offset=100, size=4."""
        parsed = parse_s7_address("MD100")
        assert parsed.area == S7AreaType.M
        assert parsed.offset == 100
        assert parsed.size == 4

    # --- Input addresses ---

    def test_parse_input_bit(self) -> None:
        """I0.0 → area=I, offset=0, bit=0."""
        parsed = parse_s7_address("I0.0")
        assert parsed.area == S7AreaType.I
        assert parsed.offset == 0
        assert parsed.bit_offset == 0

    def test_parse_input_bit_alt(self) -> None:
        """I1.3 → area=I, offset=1, bit=3."""
        parsed = parse_s7_address("I1.3")
        assert parsed.area == S7AreaType.I
        assert parsed.offset == 1
        assert parsed.bit_offset == 3

    def test_parse_input_byte(self) -> None:
        """IB0 → area=I, offset=0, size=1."""
        parsed = parse_s7_address("IB0")
        assert parsed.area == S7AreaType.I
        assert parsed.offset == 0
        assert parsed.size == 1

    def test_parse_input_word(self) -> None:
        """IW0 → area=I, offset=0, size=2."""
        parsed = parse_s7_address("IW0")
        assert parsed.area == S7AreaType.I
        assert parsed.offset == 0
        assert parsed.size == 2

    # --- Output addresses ---

    def test_parse_output_bit(self) -> None:
        """Q0.0 → area=Q, offset=0, bit=0."""
        parsed = parse_s7_address("Q0.0")
        assert parsed.area == S7AreaType.Q
        assert parsed.offset == 0
        assert parsed.bit_offset == 0

    def test_parse_output_byte(self) -> None:
        """QB4 → area=Q, offset=4, size=1."""
        parsed = parse_s7_address("QB4")
        assert parsed.area == S7AreaType.Q
        assert parsed.offset == 4
        assert parsed.size == 1

    def test_parse_output_word(self) -> None:
        """QW0 → area=Q, offset=0, size=2."""
        parsed = parse_s7_address("QW0")
        assert parsed.area == S7AreaType.Q
        assert parsed.offset == 0
        assert parsed.size == 2

    # --- Case insensitivity ---

    def test_parse_lowercase(self) -> None:
        """db100.dbd0 should be parsed same as DB100.DBD0."""
        parsed = parse_s7_address("db100.dbd0")
        assert parsed.area == S7AreaType.DB
        assert parsed.db_number == 100
        assert parsed.offset == 0

    def test_parse_mixed_case(self) -> None:
        """Db100.DbD0 should be parsed same as DB100.DBD0."""
        parsed = parse_s7_address("Db100.DbD0")
        assert parsed.area == S7AreaType.DB
        assert parsed.db_number == 100

    # --- Whitespace handling ---

    def test_parse_with_whitespace(self) -> None:
        """Address with leading/trailing whitespace."""
        parsed = parse_s7_address("  DB100.DBD0  ")
        assert parsed.area == S7AreaType.DB
        assert parsed.db_number == 100

    # --- Invalid addresses ---

    def test_invalid_address_raises(self) -> None:
        """Invalid addresses should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid S7 address"):
            parse_s7_address("INVALID")

    def test_empty_address_raises(self) -> None:
        """Empty address should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid S7 address"):
            parse_s7_address("")

    def test_malformed_db_address_raises(self) -> None:
        """Malformed DB address should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid S7 address"):
            parse_s7_address("DB100")  # Missing data type

    def test_invalid_bit_offset_raises(self) -> None:
        """Bit offset > 7 should raise ValueError."""
        with pytest.raises(ValueError, match="Bit offset"):
            parse_s7_address("DB100.DBX0.8")


# =============================================================================
# S7 DATA ENCODING/DECODING TESTS
# =============================================================================


class TestS7DataConversion:
    """Tests for S7 data type encoding and decoding."""

    # --- Decoding tests ---

    def test_decode_float(self) -> None:
        """Decode 4-byte buffer to float32 (IEEE 754)."""
        # 1.5 in IEEE 754 single precision = 0x3FC00000
        raw_bytes = struct.pack(">f", 1.5)
        result = decode_s7_value(raw_bytes, "DBD", as_float=True)
        assert abs(result - 1.5) < 0.0001

    def test_decode_float_negative(self) -> None:
        """Decode negative float."""
        raw_bytes = struct.pack(">f", -42.5)
        result = decode_s7_value(raw_bytes, "DBD", as_float=True)
        assert abs(result - (-42.5)) < 0.0001

    def test_decode_dint(self) -> None:
        """Decode 4-byte buffer to int32 (DINT)."""
        raw_bytes = struct.pack(">i", 123456)
        result = decode_s7_value(raw_bytes, "DBD", as_float=False)
        assert result == 123456

    def test_decode_dint_negative(self) -> None:
        """Decode negative int32."""
        raw_bytes = struct.pack(">i", -98765)
        result = decode_s7_value(raw_bytes, "DBD", as_float=False)
        assert result == -98765

    def test_decode_int(self) -> None:
        """Decode 2-byte buffer to int16 (INT)."""
        raw_bytes = struct.pack(">h", 1234)
        result = decode_s7_value(raw_bytes, "DBW")
        assert result == 1234

    def test_decode_int_negative(self) -> None:
        """Decode negative int16."""
        raw_bytes = struct.pack(">h", -5678)
        result = decode_s7_value(raw_bytes, "DBW")
        assert result == -5678

    def test_decode_word_unsigned(self) -> None:
        """Decode 2-byte buffer to uint16 (WORD)."""
        raw_bytes = struct.pack(">H", 65000)
        result = decode_s7_value(raw_bytes, "DBW", signed=False)
        assert result == 65000

    def test_decode_byte(self) -> None:
        """Decode 1-byte buffer to uint8."""
        raw_bytes = bytes([200])
        result = decode_s7_value(raw_bytes, "DBB")
        assert result == 200

    def test_decode_bool_true(self) -> None:
        """Decode bit from byte buffer - bit set."""
        raw_bytes = bytes([0b00000001])  # Bit 0 set
        result = decode_s7_value(raw_bytes, "DBX", bit_offset=0)
        assert result is True

    def test_decode_bool_false(self) -> None:
        """Decode bit from byte buffer - bit clear."""
        raw_bytes = bytes([0b00000000])
        result = decode_s7_value(raw_bytes, "DBX", bit_offset=0)
        assert result is False

    def test_decode_bool_specific_bit(self) -> None:
        """Decode specific bit from byte buffer."""
        raw_bytes = bytes([0b00100000])  # Bit 5 set
        result = decode_s7_value(raw_bytes, "DBX", bit_offset=5)
        assert result is True
        result = decode_s7_value(raw_bytes, "DBX", bit_offset=4)
        assert result is False

    def test_decode_memory_word(self) -> None:
        """Decode MW (Memory Word)."""
        raw_bytes = struct.pack(">h", 4096)
        result = decode_s7_value(raw_bytes, "MW")
        assert result == 4096

    def test_decode_memory_double_word(self) -> None:
        """Decode MD (Memory Double Word)."""
        raw_bytes = struct.pack(">f", 3.14159)
        result = decode_s7_value(raw_bytes, "MD", as_float=True)
        assert abs(result - 3.14159) < 0.0001

    # --- Encoding tests ---

    def test_encode_float(self) -> None:
        """Encode float32 to 4-byte buffer."""
        result = encode_s7_value(2.5, "DBD", as_float=True)
        assert len(result) == 4
        # Verify by decoding
        decoded = struct.unpack(">f", result)[0]
        assert abs(decoded - 2.5) < 0.0001

    def test_encode_dint(self) -> None:
        """Encode int32 (DINT) to 4-byte buffer."""
        result = encode_s7_value(654321, "DBD", as_float=False)
        assert len(result) == 4
        decoded = struct.unpack(">i", result)[0]
        assert decoded == 654321

    def test_encode_int(self) -> None:
        """Encode int16 (INT) to 2-byte buffer."""
        result = encode_s7_value(1000, "DBW")
        assert len(result) == 2
        decoded = struct.unpack(">h", result)[0]
        assert decoded == 1000

    def test_encode_byte(self) -> None:
        """Encode byte to 1-byte buffer."""
        result = encode_s7_value(128, "DBB")
        assert len(result) == 1
        assert result[0] == 128

    def test_encode_bool_true(self) -> None:
        """Encode True to bit in byte buffer."""
        result = encode_s7_value(True, "DBX", bit_offset=0)
        assert len(result) == 1
        assert result[0] & 0x01 == 1

    def test_encode_bool_false(self) -> None:
        """Encode False to bit in byte buffer."""
        result = encode_s7_value(False, "DBX", bit_offset=0)
        assert len(result) == 1
        assert result[0] & 0x01 == 0

    def test_encode_bool_specific_bit(self) -> None:
        """Encode bool to specific bit position."""
        result = encode_s7_value(True, "DBX", bit_offset=5)
        assert len(result) == 1
        assert result[0] == 0b00100000


# =============================================================================
# S7 CONNECTOR TESTS (MOCKED)
# =============================================================================


class TestS7ConnectorMocked:
    """Tests for S7Connector with mocked snap7 client."""

    @pytest.fixture
    def s7_config(self) -> S7ConnectorConfig:
        """Create test S7 connector configuration."""
        return S7ConnectorConfig(
            name="test_s7",
            host="192.168.1.100",
            rack=0,
            slot=1,
            port=102,
        )

    @pytest.fixture
    def mock_snap7_client(self) -> MagicMock:
        """Create mock snap7 client."""
        mock_client = MagicMock()
        mock_client.connect.return_value = None  # connect() returns None on success
        mock_client.disconnect.return_value = None
        mock_client.get_connected.return_value = True
        return mock_client

    async def test_connect_success(self, s7_config: S7ConnectorConfig) -> None:
        """Successful connection sets state to CONNECTED."""
        with (
            patch("mtp_gateway.adapters.southbound.s7.driver.snap7") as mock_snap7,
            patch("mtp_gateway.adapters.southbound.s7.driver.HAS_SNAP7", True),
        ):
            mock_client = MagicMock()
            mock_client.connect.return_value = None
            mock_client.get_connected.return_value = True
            mock_snap7.client.Client.return_value = mock_client

            connector = S7Connector(s7_config)
            await connector.connect()

            health = connector.health_status()
            assert health.state == ConnectorState.CONNECTED
            mock_client.connect.assert_called_once_with("192.168.1.100", 0, 1, 102)

    async def test_connect_failure_sets_error(self, s7_config: S7ConnectorConfig) -> None:
        """Connection failure sets ERROR state."""
        with (
            patch("mtp_gateway.adapters.southbound.s7.driver.snap7") as mock_snap7,
            patch("mtp_gateway.adapters.southbound.s7.driver.HAS_SNAP7", True),
        ):
            mock_client = MagicMock()
            mock_client.connect.side_effect = Exception("Connection refused")
            mock_snap7.client.Client.return_value = mock_client

            connector = S7Connector(s7_config)

            with pytest.raises(ConnectionError):
                await connector.connect()

            health = connector.health_status()
            assert health.state == ConnectorState.ERROR

    async def test_read_tags_returns_tag_values(self, s7_config: S7ConnectorConfig) -> None:
        """Reading tags returns dict of TagValue objects."""
        with (
            patch("mtp_gateway.adapters.southbound.s7.driver.snap7") as mock_snap7,
            patch("mtp_gateway.adapters.southbound.s7.driver.HAS_SNAP7", True),
        ):
            mock_client = MagicMock()
            mock_client.connect.return_value = None
            mock_client.get_connected.return_value = True
            # Return 4 bytes for a float (DB100.DBD0)
            mock_client.db_read.return_value = bytearray(struct.pack(">f", 25.5))
            mock_snap7.client.Client.return_value = mock_client

            connector = S7Connector(s7_config)
            await connector.connect()

            result = await connector.read_tags(["DB100.DBD0"])

            assert "DB100.DBD0" in result
            tag_value = result["DB100.DBD0"]
            assert tag_value.quality == Quality.GOOD
            assert abs(tag_value.value - 25.5) < 0.0001

    async def test_read_multiple_tags(self, s7_config: S7ConnectorConfig) -> None:
        """Reading multiple tags returns all values."""
        with (
            patch("mtp_gateway.adapters.southbound.s7.driver.snap7") as mock_snap7,
            patch("mtp_gateway.adapters.southbound.s7.driver.HAS_SNAP7", True),
        ):
            mock_client = MagicMock()
            mock_client.connect.return_value = None
            mock_client.get_connected.return_value = True

            def mock_db_read(db_number: int, start: int, size: int) -> bytearray:
                if db_number == 100 and start == 0:
                    return bytearray(struct.pack(">f", 10.0))
                elif db_number == 100 and start == 4:
                    return bytearray(struct.pack(">f", 20.0))
                return bytearray(size)

            mock_client.db_read.side_effect = mock_db_read
            mock_snap7.client.Client.return_value = mock_client

            connector = S7Connector(s7_config)
            await connector.connect()

            result = await connector.read_tags(["DB100.DBD0", "DB100.DBD4"])

            assert len(result) == 2
            assert "DB100.DBD0" in result
            assert "DB100.DBD4" in result

    async def test_read_failure_returns_bad_quality(self, s7_config: S7ConnectorConfig) -> None:
        """Read errors return bad quality (specific code depends on error handling)."""
        with (
            patch("mtp_gateway.adapters.southbound.s7.driver.snap7") as mock_snap7,
            patch("mtp_gateway.adapters.southbound.s7.driver.HAS_SNAP7", True),
        ):
            mock_client = MagicMock()
            mock_client.connect.return_value = None
            mock_client.get_connected.return_value = True
            mock_client.db_read.side_effect = Exception("Read timeout")
            mock_snap7.client.Client.return_value = mock_client

            connector = S7Connector(s7_config)
            await connector.connect()

            result = await connector.read_tags(["DB100.DBD0"])

            assert "DB100.DBD0" in result
            # Individual address failures result in BAD_CONFIG_ERROR
            # Batch failures would result in BAD_NO_COMMUNICATION
            assert result["DB100.DBD0"].quality.is_bad()

    async def test_read_memory_area(self, s7_config: S7ConnectorConfig) -> None:
        """Read from memory area (M)."""
        with (
            patch("mtp_gateway.adapters.southbound.s7.driver.snap7") as mock_snap7,
            patch("mtp_gateway.adapters.southbound.s7.driver.HAS_SNAP7", True),
        ):
            mock_client = MagicMock()
            mock_client.connect.return_value = None
            mock_client.get_connected.return_value = True
            # Return 2 bytes for a word (MW100)
            mock_client.read_area.return_value = bytearray(struct.pack(">h", 1234))
            mock_snap7.client.Client.return_value = mock_client

            connector = S7Connector(s7_config)
            await connector.connect()

            result = await connector.read_tags(["MW100"])

            assert "MW100" in result
            assert result["MW100"].value == 1234

    async def test_read_input_area(self, s7_config: S7ConnectorConfig) -> None:
        """Read from input area (I)."""
        with (
            patch("mtp_gateway.adapters.southbound.s7.driver.snap7") as mock_snap7,
            patch("mtp_gateway.adapters.southbound.s7.driver.HAS_SNAP7", True),
        ):
            mock_client = MagicMock()
            mock_client.connect.return_value = None
            mock_client.get_connected.return_value = True
            # Return 1 byte with bit 0 set
            mock_client.read_area.return_value = bytearray([0b00000001])
            mock_snap7.client.Client.return_value = mock_client

            connector = S7Connector(s7_config)
            await connector.connect()

            result = await connector.read_tags(["I0.0"])

            assert "I0.0" in result
            assert result["I0.0"].value is True

    async def test_write_tag_success(self, s7_config: S7ConnectorConfig) -> None:
        """Write returns True on success."""
        with (
            patch("mtp_gateway.adapters.southbound.s7.driver.snap7") as mock_snap7,
            patch("mtp_gateway.adapters.southbound.s7.driver.HAS_SNAP7", True),
        ):
            mock_client = MagicMock()
            mock_client.connect.return_value = None
            mock_client.get_connected.return_value = True
            mock_client.db_write.return_value = None
            mock_snap7.client.Client.return_value = mock_client

            connector = S7Connector(s7_config)
            await connector.connect()

            result = await connector.write_tag("DB100.DBD0", 42.5)

            assert result is True
            mock_client.db_write.assert_called_once()

    async def test_write_tag_failure(self, s7_config: S7ConnectorConfig) -> None:
        """Write returns False on failure."""
        with (
            patch("mtp_gateway.adapters.southbound.s7.driver.snap7") as mock_snap7,
            patch("mtp_gateway.adapters.southbound.s7.driver.HAS_SNAP7", True),
        ):
            mock_client = MagicMock()
            mock_client.connect.return_value = None
            mock_client.get_connected.return_value = True
            mock_client.db_write.side_effect = Exception("Write error")
            mock_snap7.client.Client.return_value = mock_client

            connector = S7Connector(s7_config)
            await connector.connect()

            result = await connector.write_tag("DB100.DBD0", 42.5)

            assert result is False

    async def test_write_to_memory_area(self, s7_config: S7ConnectorConfig) -> None:
        """Write to memory area."""
        with (
            patch("mtp_gateway.adapters.southbound.s7.driver.snap7") as mock_snap7,
            patch("mtp_gateway.adapters.southbound.s7.driver.HAS_SNAP7", True),
        ):
            mock_client = MagicMock()
            mock_client.connect.return_value = None
            mock_client.get_connected.return_value = True
            mock_client.write_area.return_value = None
            mock_snap7.client.Client.return_value = mock_client

            connector = S7Connector(s7_config)
            await connector.connect()

            result = await connector.write_tag("MW100", 5000)

            assert result is True
            mock_client.write_area.assert_called_once()

    async def test_write_output_bit(self, s7_config: S7ConnectorConfig) -> None:
        """Write to output bit."""
        with (
            patch("mtp_gateway.adapters.southbound.s7.driver.snap7") as mock_snap7,
            patch("mtp_gateway.adapters.southbound.s7.driver.HAS_SNAP7", True),
        ):
            mock_client = MagicMock()
            mock_client.connect.return_value = None
            mock_client.get_connected.return_value = True
            mock_client.write_area.return_value = None
            mock_snap7.client.Client.return_value = mock_client

            connector = S7Connector(s7_config)
            await connector.connect()

            result = await connector.write_tag("Q0.0", True)

            assert result is True

    async def test_disconnect_graceful(self, s7_config: S7ConnectorConfig) -> None:
        """Disconnect closes client cleanly."""
        with (
            patch("mtp_gateway.adapters.southbound.s7.driver.snap7") as mock_snap7,
            patch("mtp_gateway.adapters.southbound.s7.driver.HAS_SNAP7", True),
        ):
            mock_client = MagicMock()
            mock_client.connect.return_value = None
            mock_client.get_connected.return_value = True
            mock_snap7.client.Client.return_value = mock_client

            connector = S7Connector(s7_config)
            await connector.connect()
            await connector.disconnect()

            mock_client.disconnect.assert_called_once()
            health = connector.health_status()
            assert health.state == ConnectorState.STOPPED

    async def test_read_without_connect_fails(self, s7_config: S7ConnectorConfig) -> None:
        """Reading without connecting returns bad quality."""
        with (
            patch("mtp_gateway.adapters.southbound.s7.driver.snap7"),
            patch("mtp_gateway.adapters.southbound.s7.driver.HAS_SNAP7", True),
        ):
            connector = S7Connector(s7_config)

            result = await connector.read_tags(["DB100.DBD0"])

            assert "DB100.DBD0" in result
            assert result["DB100.DBD0"].quality.is_bad()
