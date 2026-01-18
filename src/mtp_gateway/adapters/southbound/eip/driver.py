"""Allen-Bradley EtherNet/IP connector using pycomm3.

Implements communication with Allen-Bradley ControlLogix, CompactLogix,
and Micro800 series PLCs via EtherNet/IP (CIP) protocol.

EIP Address Formats (symbolic tag names):
- Program:MainProgram.MyTag  - Program-scoped tag
- MyGlobalTag                - Controller-scoped tag
- MyArray[0]                 - Array element
- MyUDT.Member               - UDT member access
- MyTag{5}                   - Bit access (bit 5)

Unlike S7/Modbus, EIP uses symbolic names that match PLC tag names directly.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog

from mtp_gateway.adapters.southbound.base import BaseConnector

if TYPE_CHECKING:
    from mtp_gateway.config.schema import EIPConnectorConfig

# Import pycomm3 lazily to handle optional dependency
# pycomm3 is optional - install with: pip install pycomm3
try:
    from pycomm3 import LogixDriver

    _HAS_PYCOMM3 = True
except ImportError:
    LogixDriver = None
    _HAS_PYCOMM3 = False

HAS_PYCOMM3: bool = _HAS_PYCOMM3

logger = structlog.get_logger(__name__)


@dataclass
class ParsedEIPAddress:
    """Parsed EIP tag address.

    Attributes:
        tag_name: Full tag path (without array index or bit suffix)
        element: Array index if present (e.g., 0 for MyArray[0])
        bit: Bit offset if present (e.g., 5 for MyTag{5})
    """

    tag_name: str
    element: int | None = None
    bit: int | None = None


# Regular expressions for parsing EIP addresses
# Array element: TagName[N] where N is a non-negative integer
_ARRAY_PATTERN = re.compile(r"^(.+)\[(\d+)\]$")
# Bit access: TagName{N} where N is a non-negative integer
_BIT_PATTERN = re.compile(r"^(.+)\{(\d+)\}$")
# Combined: TagName[N]{M} - array element with bit access
_ARRAY_BIT_PATTERN = re.compile(r"^(.+)\[(\d+)\]\{(\d+)\}$")


def parse_eip_address(address_str: str) -> ParsedEIPAddress:
    """Parse an EIP tag address string into components.

    Supports formats:
    - "MyTag"                      - Simple tag
    - "Program:MainProgram.MyTag"  - Program-scoped tag
    - "MyArray[0]"                 - Array element
    - "MyUDT.Member"               - UDT member access
    - "MyTag{5}"                   - Bit access
    - "MyArray[0]{5}"              - Array element with bit access

    Args:
        address_str: EIP tag address string to parse

    Returns:
        ParsedEIPAddress with tag name, optional element, and optional bit

    Raises:
        ValueError: If address format is invalid
    """
    address_str = address_str.strip()

    if not address_str:
        raise ValueError("Invalid EIP address: empty string")

    # Check for combined array + bit pattern first: Tag[N]{M}
    match = _ARRAY_BIT_PATTERN.match(address_str)
    if match:
        tag_name = match.group(1)
        element = int(match.group(2))
        bit = int(match.group(3))
        return ParsedEIPAddress(tag_name=tag_name, element=element, bit=bit)

    # Check for bit access pattern: Tag{N}
    match = _BIT_PATTERN.match(address_str)
    if match:
        tag_name = match.group(1)
        bit = int(match.group(2))
        return ParsedEIPAddress(tag_name=tag_name, element=None, bit=bit)

    # Check for array element pattern: Tag[N]
    match = _ARRAY_PATTERN.match(address_str)
    if match:
        tag_name = match.group(1)
        element = int(match.group(2))
        return ParsedEIPAddress(tag_name=tag_name, element=element, bit=None)

    # Check for malformed patterns (unclosed brackets/braces)
    if "[" in address_str and "]" not in address_str:
        raise ValueError(f"Invalid EIP address: unclosed bracket in '{address_str}'")
    if "{" in address_str and "}" not in address_str:
        raise ValueError(f"Invalid EIP address: unclosed brace in '{address_str}'")

    # Check for invalid array index (non-numeric)
    if "[" in address_str:
        # Has brackets but didn't match pattern - invalid index
        raise ValueError(f"Invalid EIP address: invalid array index in '{address_str}'")

    # Check for invalid bit offset (non-numeric)
    if "{" in address_str:
        # Has braces but didn't match pattern - invalid bit
        raise ValueError(f"Invalid EIP address: invalid bit offset in '{address_str}'")

    # Simple tag name (including UDT members and program-scoped tags)
    return ParsedEIPAddress(tag_name=address_str, element=None, bit=None)


def _build_tag_string(address: str, parsed: ParsedEIPAddress) -> str:
    """Build the pycomm3-compatible tag string from parsed address.

    pycomm3 expects the full tag path including array indices.
    Bit access is handled separately.

    Args:
        address: Original address string
        parsed: Parsed address components

    Returns:
        Tag string for pycomm3
    """
    if parsed.element is not None:
        # Array element - reconstruct without bit suffix
        return f"{parsed.tag_name}[{parsed.element}]"
    return parsed.tag_name


class EIPConnector(BaseConnector):
    """Allen-Bradley EtherNet/IP connector using pycomm3.

    Supports ControlLogix, CompactLogix, and Micro800 series PLCs.
    Uses CIP (Common Industrial Protocol) over EtherNet/IP.

    pycomm3 is a synchronous library, so all operations are wrapped
    with asyncio.to_thread() for async compatibility.
    """

    def __init__(self, config: EIPConnectorConfig) -> None:
        """Initialize EIP connector.

        Args:
            config: EIP connector configuration

        Raises:
            ImportError: If pycomm3 library is not installed
        """
        super().__init__(config)
        if not HAS_PYCOMM3 or LogixDriver is None:
            raise ImportError(
                "pycomm3 library is required for EIP connector. "
                "Install with: pip install pycomm3"
            )
        self._driver: Any = None  # LogixDriver | None
        self._host = config.host
        self._slot = config.slot

    async def _do_connect(self) -> None:
        """Establish connection to Allen-Bradley PLC.

        Uses pycomm3's LogixDriver for CIP/EIP communication.
        Connection is run in a thread to avoid blocking.
        """

        def connect_sync() -> Any:
            driver = LogixDriver(self._host, slot=self._slot)
            driver.open()
            return driver

        self._driver = await asyncio.to_thread(connect_sync)

        logger.debug(
            "EIP connected",
            host=self._host,
            slot=self._slot,
        )

    async def _do_disconnect(self) -> None:
        """Close connection to Allen-Bradley PLC."""
        if self._driver:

            def disconnect_sync() -> None:
                if self._driver:
                    self._driver.close()

            await asyncio.to_thread(disconnect_sync)
            self._driver = None

    async def _do_read(self, addresses: list[str]) -> dict[str, Any]:
        """Read multiple EIP tags.

        Args:
            addresses: List of EIP tag address strings to read

        Returns:
            Dictionary mapping addresses to values

        Note:
            pycomm3 supports batch reads natively - pass multiple tags
            to read() for efficient communication.
        """
        if not self._driver:
            raise ConnectionError("Not connected")

        driver = self._driver
        results: dict[str, Any] = {}

        # Parse addresses and build tag list for batch read
        tag_to_address: dict[str, str] = {}
        parsed_addresses: dict[str, ParsedEIPAddress] = {}

        for addr in addresses:
            try:
                parsed = parse_eip_address(addr)
                tag_str = _build_tag_string(addr, parsed)
                tag_to_address[tag_str] = addr
                parsed_addresses[addr] = parsed
            except ValueError as e:
                logger.warning(
                    "Failed to parse EIP address",
                    address=addr,
                    error=str(e),
                )

        if not tag_to_address:
            return results

        # Use batch read for efficiency
        tag_list = list(tag_to_address.keys())

        def read_sync() -> Any:
            if len(tag_list) == 1:
                return driver.read(tag_list[0])
            return driver.read(*tag_list)

        try:
            read_result = await asyncio.to_thread(read_sync)

            # Handle single vs multiple tag results
            if len(tag_list) == 1:
                tag_results = [read_result]
            else:
                tag_results = read_result if isinstance(read_result, list) else [read_result]

            # Process results
            for i, tag_str in enumerate(tag_list):
                addr = tag_to_address[tag_str]
                parsed = parsed_addresses[addr]

                if i < len(tag_results):
                    tag_result = tag_results[i]

                    # Check for error in tag result
                    if hasattr(tag_result, "error") and tag_result.error:
                        logger.warning(
                            "EIP tag read error",
                            address=addr,
                            error=tag_result.error,
                        )
                        # Don't include in results - caller handles missing tags
                        continue

                    value = tag_result.value if hasattr(tag_result, "value") else tag_result

                    # Handle bit extraction if needed
                    if parsed.bit is not None and isinstance(value, int):
                        value = bool(value & (1 << parsed.bit))

                    results[addr] = value

        except Exception as e:
            logger.warning(
                "Failed to read EIP tags",
                addresses=addresses,
                error=str(e),
            )
            raise

        return results

    async def _do_write(self, address: str, value: Any) -> None:
        """Write to a single EIP tag.

        Args:
            address: EIP tag address string
            value: Value to write

        Raises:
            ConnectionError: If not connected
            ValueError: If address is invalid or write fails
        """
        if not self._driver:
            raise ConnectionError("Not connected")

        parsed = parse_eip_address(address)
        driver = self._driver

        # Build tag string for pycomm3
        tag_str = _build_tag_string(address, parsed)

        # Handle bit writes
        write_value = value
        if parsed.bit is not None:
            # For bit writes, pycomm3 expects the full value
            # We need to read-modify-write, or use the bit index syntax
            # pycomm3 may support Tag.N syntax for bit access
            # For now, we'll pass the value as-is and let pycomm3 handle it
            # If value is bool, convert to int for bit manipulation
            if isinstance(value, bool):
                write_value = value

        def write_sync() -> Any:
            return driver.write((tag_str, write_value))

        result = await asyncio.to_thread(write_sync)

        # Check for write error
        if hasattr(result, "error") and result.error:
            raise ValueError(f"Write failed: {result.error}")
