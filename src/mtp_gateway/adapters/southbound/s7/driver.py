"""Siemens S7 PLC connector using python-snap7.

Implements communication with Siemens S7-300/400/1200/1500 PLCs.
Uses snap7 library for the underlying protocol implementation.

S7 Address Formats:
- DB100.DBD0  - Data Block 100, Double Word at offset 0 (float/dint)
- DB100.DBW10 - Data Block 100, Word at offset 10 (int16)
- DB100.DBB20 - Data Block 100, Byte at offset 20
- DB100.DBX30.0 - Data Block 100, Bit 0 at byte offset 30
- M0.0  - Memory/Marker bit
- MW100 - Memory word
- I0.0  - Input bit
- Q0.0  - Output bit
"""

from __future__ import annotations

import asyncio
import re
import struct
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

import structlog

from mtp_gateway.adapters.southbound.base import BaseConnector

if TYPE_CHECKING:
    from mtp_gateway.config.schema import S7ConnectorConfig

# Import snap7 lazily to handle optional dependency
# snap7 is optional - install with: pip install python-snap7
try:
    import snap7
    import snap7.client

    _HAS_SNAP7 = True
except ImportError:
    snap7 = None
    _HAS_SNAP7 = False

HAS_SNAP7: bool = _HAS_SNAP7

logger = structlog.get_logger(__name__)


class S7AreaType(Enum):
    """S7 memory areas."""

    DB = "db"  # Data blocks
    M = "m"  # Marker/Memory
    I = "i"  # noqa: E741  # Inputs (PE - Process image inputs)
    Q = "q"  # Outputs (PA - Process image outputs)
    C = "c"  # Counters
    T = "t"  # Timers


# snap7 area codes
S7_AREA_CODES: dict[S7AreaType, int] = {
    S7AreaType.DB: 0x84,  # Data Block
    S7AreaType.M: 0x83,  # Markers
    S7AreaType.I: 0x81,  # Inputs
    S7AreaType.Q: 0x82,  # Outputs
    S7AreaType.C: 0x1C,  # Counters
    S7AreaType.T: 0x1D,  # Timers
}


@dataclass
class ParsedS7Address:
    """Parsed S7 address components.

    Attributes:
        area: Memory area type (DB, M, I, Q, C, T)
        db_number: Data block number (only for DB areas)
        offset: Byte offset within the area
        bit_offset: Bit offset within the byte (0-7, only for bit access)
        size: Number of bytes to read/write
        data_type: Original data type string (DBD, DBW, DBB, DBX, etc.)
    """

    area: S7AreaType
    db_number: int | None
    offset: int
    bit_offset: int | None
    size: int
    data_type: str


# Regular expressions for parsing S7 addresses
# DB addresses: DB<num>.DB<type><offset>[.<bit>]
_DB_PATTERN = re.compile(
    r"^DB(\d+)\.DB([DWBX])(\d+)(?:\.(\d+))?$",
    re.IGNORECASE,
)

# Memory/Marker: M<offset>.<bit> or M[BWD]<offset>
_M_BIT_PATTERN = re.compile(r"^M(\d+)\.([0-7])$", re.IGNORECASE)
_M_DATA_PATTERN = re.compile(r"^M([BWD])(\d+)$", re.IGNORECASE)

# Input/Output: I/Q<offset>.<bit> or I/Q[BWD]<offset>
_IO_BIT_PATTERN = re.compile(r"^([IQ])(\d+)\.([0-7])$", re.IGNORECASE)
_IO_DATA_PATTERN = re.compile(r"^([IQ])([BWD])(\d+)$", re.IGNORECASE)


def parse_s7_address(address_str: str) -> ParsedS7Address:  # noqa: PLR0912
    """Parse an S7 address string into components.

    Supports formats:
    - "DB100.DBD0" - Data Block double word
    - "DB100.DBW10" - Data Block word
    - "DB100.DBB20" - Data Block byte
    - "DB100.DBX30.0" - Data Block bit
    - "M0.0" - Memory bit
    - "MB100", "MW100", "MD100" - Memory byte/word/dword
    - "I0.0", "Q0.0" - Input/Output bit
    - "IB0", "IW0", "QB0", "QW0" - Input/Output byte/word

    Args:
        address_str: S7 address string to parse

    Returns:
        ParsedS7Address with area, offset, and size information

    Raises:
        ValueError: If address format is invalid
    """
    address_str = address_str.strip().upper()

    if not address_str:
        raise ValueError("Invalid S7 address: empty string")

    # Try DB address pattern
    match = _DB_PATTERN.match(address_str)
    if match:
        db_num = int(match.group(1))
        data_type = match.group(2).upper()
        offset = int(match.group(3))
        bit_str = match.group(4)

        bit_offset = None
        if data_type == "X":
            if bit_str is None:
                raise ValueError(f"Invalid S7 address: DBX requires bit offset: {address_str}")
            bit_offset = int(bit_str)
            if bit_offset > 7:
                raise ValueError(f"Bit offset must be 0-7, got {bit_offset}")
            size = 1
        elif data_type == "D":
            size = 4
        elif data_type == "W":
            size = 2
        elif data_type == "B":
            size = 1
        else:
            raise ValueError(f"Invalid S7 address: unknown data type {data_type}")

        return ParsedS7Address(
            area=S7AreaType.DB,
            db_number=db_num,
            offset=offset,
            bit_offset=bit_offset,
            size=size,
            data_type=f"DB{data_type}",
        )

    # Try Memory bit pattern (M0.0)
    match = _M_BIT_PATTERN.match(address_str)
    if match:
        offset = int(match.group(1))
        bit_offset = int(match.group(2))
        return ParsedS7Address(
            area=S7AreaType.M,
            db_number=None,
            offset=offset,
            bit_offset=bit_offset,
            size=1,
            data_type="M",
        )

    # Try Memory data pattern (MB100, MW100, MD100)
    match = _M_DATA_PATTERN.match(address_str)
    if match:
        data_type = match.group(1).upper()
        offset = int(match.group(2))
        size = {"B": 1, "W": 2, "D": 4}[data_type]
        return ParsedS7Address(
            area=S7AreaType.M,
            db_number=None,
            offset=offset,
            bit_offset=None,
            size=size,
            data_type=f"M{data_type}",
        )

    # Try I/Q bit pattern (I0.0, Q0.0)
    match = _IO_BIT_PATTERN.match(address_str)
    if match:
        area_char = match.group(1).upper()
        offset = int(match.group(2))
        bit_offset = int(match.group(3))
        area = S7AreaType.I if area_char == "I" else S7AreaType.Q
        return ParsedS7Address(
            area=area,
            db_number=None,
            offset=offset,
            bit_offset=bit_offset,
            size=1,
            data_type=area_char,
        )

    # Try I/Q data pattern (IB0, IW0, QB0, QW0, etc.)
    match = _IO_DATA_PATTERN.match(address_str)
    if match:
        area_char = match.group(1).upper()
        data_type = match.group(2).upper()
        offset = int(match.group(3))
        area = S7AreaType.I if area_char == "I" else S7AreaType.Q
        size = {"B": 1, "W": 2, "D": 4}[data_type]
        return ParsedS7Address(
            area=area,
            db_number=None,
            offset=offset,
            bit_offset=None,
            size=size,
            data_type=f"{area_char}{data_type}",
        )

    raise ValueError(f"Invalid S7 address: {address_str}")


def decode_s7_value(  # noqa: PLR0911
    raw_bytes: bytes | bytearray,
    data_type: str,
    *,
    as_float: bool = False,
    signed: bool = True,
    bit_offset: int | None = None,
) -> float | int | bool:
    """Decode raw bytes from S7 PLC to Python value.

    Args:
        raw_bytes: Raw bytes read from PLC
        data_type: Data type string (DBD, DBW, DBB, DBX, MW, MD, etc.)
        as_float: If True, decode 4-byte values as float32 instead of int32
        signed: If True, decode integers as signed
        bit_offset: Bit offset for bit access (0-7)

    Returns:
        Decoded Python value (float, int, or bool)
    """
    data_type = data_type.upper()

    # Bit access (DBX, M bit, I bit, Q bit)
    if data_type in ("DBX", "M", "I", "Q") or bit_offset is not None:
        if bit_offset is None:
            bit_offset = 0
        byte_val = raw_bytes[0] if raw_bytes else 0
        return bool(byte_val & (1 << bit_offset))

    # Byte access (DBB, MB, IB, QB)
    if data_type.endswith("B"):
        return raw_bytes[0] if raw_bytes else 0

    # Word access (DBW, MW, IW, QW) - 2 bytes
    if data_type.endswith("W"):
        if len(raw_bytes) < 2:
            return 0
        fmt = ">h" if signed else ">H"
        result: int = struct.unpack(fmt, raw_bytes[:2])[0]
        return result

    # Double word access (DBD, MD, ID, QD) - 4 bytes
    if data_type.endswith("D"):
        if len(raw_bytes) < 4:
            return 0
        if as_float:
            float_result: float = struct.unpack(">f", raw_bytes[:4])[0]
            return float_result
        fmt = ">i" if signed else ">I"
        int_result: int = struct.unpack(fmt, raw_bytes[:4])[0]
        return int_result

    # Default: treat as byte
    return raw_bytes[0] if raw_bytes else 0


def encode_s7_value(
    value: float | int | bool,
    data_type: str,
    *,
    as_float: bool = False,
    bit_offset: int | None = None,
) -> bytes:
    """Encode Python value to bytes for S7 PLC.

    Args:
        value: Python value to encode
        data_type: Data type string (DBD, DBW, DBB, DBX, MW, etc.)
        as_float: If True, encode as float32 for 4-byte values
        bit_offset: Bit offset for bit access (0-7)

    Returns:
        Encoded bytes for writing to PLC
    """
    data_type = data_type.upper()

    # Bit access (DBX, M bit, I bit, Q bit)
    if data_type in ("DBX", "M", "I", "Q") or bit_offset is not None:
        if bit_offset is None:
            bit_offset = 0
        byte_val = (1 << bit_offset) if bool(value) else 0
        return bytes([byte_val])

    # Byte access (DBB, MB, IB, QB)
    if data_type.endswith("B"):
        return bytes([int(value) & 0xFF])

    # Word access (DBW, MW, IW, QW) - 2 bytes
    if data_type.endswith("W"):
        return struct.pack(">h", int(value))

    # Double word access (DBD, MD, ID, QD) - 4 bytes
    if data_type.endswith("D"):
        if as_float:
            return struct.pack(">f", float(value))
        return struct.pack(">i", int(value))

    # Default: treat as byte
    return bytes([int(value) & 0xFF])


class S7Connector(BaseConnector):
    """Siemens S7 PLC connector using python-snap7.

    Supports S7-300, S7-400, S7-1200, and S7-1500 PLCs.
    Uses TCP/IP communication (port 102 by default).

    snap7 is a synchronous library, so all operations are wrapped
    with asyncio.to_thread() for async compatibility.
    """

    def __init__(self, config: S7ConnectorConfig) -> None:
        """Initialize S7 connector.

        Args:
            config: S7 connector configuration

        Raises:
            ImportError: If snap7 library is not installed
        """
        super().__init__(config)
        if not HAS_SNAP7 or snap7 is None:
            raise ImportError(
                "snap7 library is required for S7 connector. "
                "Install with: pip install python-snap7"
            )
        self._client: Any = None  # snap7.client.Client | None
        self._host = config.host
        self._rack = config.rack
        self._slot = config.slot
        self._port = config.port

    async def _do_connect(self) -> None:
        """Establish connection to S7 PLC.

        Uses snap7's connect method with rack and slot.
        Connection is run in a thread to avoid blocking.
        """
        self._client = snap7.client.Client()

        def connect_sync() -> None:
            if self._client is None:
                raise ConnectionError("Client not initialized")
            self._client.connect(self._host, self._rack, self._slot, self._port)
            if not self._client.get_connected():
                raise ConnectionError(f"Failed to connect to {self._host}")

        await asyncio.to_thread(connect_sync)

        logger.debug(
            "S7 connected",
            host=self._host,
            rack=self._rack,
            slot=self._slot,
        )

    async def _do_disconnect(self) -> None:
        """Close connection to S7 PLC."""
        if self._client:

            def disconnect_sync() -> None:
                if self._client:
                    self._client.disconnect()

            await asyncio.to_thread(disconnect_sync)
            self._client = None

    async def _do_read(self, addresses: list[str]) -> dict[str, Any]:
        """Read multiple S7 addresses.

        Args:
            addresses: List of S7 address strings to read

        Returns:
            Dictionary mapping addresses to decoded values

        Note:
            Currently reads each address individually.
            Future optimization: coalesce adjacent addresses.
        """
        if not self._client:
            raise ConnectionError("Not connected")

        results: dict[str, Any] = {}

        for addr_str in addresses:
            try:
                parsed = parse_s7_address(addr_str)
                value = await self._read_single(parsed)
                results[addr_str] = value
            except Exception as e:
                logger.warning(
                    "Failed to read S7 address",
                    address=addr_str,
                    error=str(e),
                )
                # Don't include failed reads - let caller handle quality

        return results

    async def _read_single(self, parsed: ParsedS7Address) -> Any:
        """Read a single S7 address.

        Args:
            parsed: Parsed S7 address

        Returns:
            Decoded value from PLC
        """
        if not self._client:
            raise ConnectionError("Not connected")

        client = self._client

        def read_sync() -> bytes:
            if parsed.area == S7AreaType.DB:
                if parsed.db_number is None:
                    raise ValueError("DB address requires db_number")
                return bytes(
                    client.db_read(parsed.db_number, parsed.offset, parsed.size)
                )
            else:
                area_code = S7_AREA_CODES[parsed.area]
                return bytes(
                    client.read_area(area_code, 0, parsed.offset, parsed.size)
                )

        raw_bytes = await asyncio.to_thread(read_sync)

        # Determine if this should be decoded as float
        # DBD with no bit offset is commonly used for floats
        as_float = parsed.data_type in ("DBD", "MD") and parsed.bit_offset is None

        return decode_s7_value(
            raw_bytes,
            parsed.data_type,
            as_float=as_float,
            bit_offset=parsed.bit_offset,
        )

    async def _do_write(self, address: str, value: Any) -> None:
        """Write to a single S7 address.

        Args:
            address: S7 address string
            value: Value to write

        Raises:
            ConnectionError: If not connected
            ValueError: If address is invalid
        """
        if not self._client:
            raise ConnectionError("Not connected")

        parsed = parse_s7_address(address)
        client = self._client

        # Determine if value should be encoded as float
        as_float = isinstance(value, float) and parsed.data_type in ("DBD", "MD")

        encoded = encode_s7_value(
            value,
            parsed.data_type,
            as_float=as_float,
            bit_offset=parsed.bit_offset,
        )

        def write_sync() -> None:
            if parsed.area == S7AreaType.DB:
                if parsed.db_number is None:
                    raise ValueError("DB address requires db_number")
                client.db_write(parsed.db_number, parsed.offset, bytearray(encoded))
            else:
                area_code = S7_AREA_CODES[parsed.area]
                client.write_area(area_code, 0, parsed.offset, bytearray(encoded))

        await asyncio.to_thread(write_sync)
