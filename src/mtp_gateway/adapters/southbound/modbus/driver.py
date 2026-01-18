"""Modbus TCP and RTU driver for MTP Gateway.

Implements communication with PLCs via Modbus TCP or Modbus RTU (serial).
Uses pymodbus for the underlying protocol implementation.

Modbus Address Mapping:
- 00001-09999: Coils (discrete outputs) - read/write bool
- 10001-19999: Discrete inputs - read-only bool
- 30001-39999: Input registers - read-only 16-bit
- 40001-49999: Holding registers - read/write 16-bit
"""

from __future__ import annotations

import asyncio
import struct
from datetime import datetime, timezone
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

import structlog
from pymodbus.client import AsyncModbusSerialClient, AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException
from pymodbus.pdu import ExceptionResponse

from mtp_gateway.adapters.southbound.base import BaseConnector

if TYPE_CHECKING:
    from pymodbus.client import ModbusBaseClient

    from mtp_gateway.config.schema import ModbusRTUConnectorConfig, ModbusTCPConnectorConfig

logger = structlog.get_logger(__name__)


class ModbusRegisterType(Enum):
    """Modbus register types determined by address range."""

    COIL = "coil"  # 00001-09999
    DISCRETE_INPUT = "discrete_input"  # 10001-19999
    INPUT_REGISTER = "input_register"  # 30001-39999
    HOLDING_REGISTER = "holding_register"  # 40001-49999


@dataclass
class ParsedAddress:
    """Parsed Modbus address with type and offset."""

    register_type: ModbusRegisterType
    address: int  # 0-based address for pymodbus
    count: int = 1  # Number of registers to read
    bit_offset: int | None = None  # For bit-level access within registers


def parse_modbus_address(address_str: str) -> ParsedAddress:
    """Parse a Modbus address string into components.

    Supports formats:
    - "40001" - Standard 5-digit Modbus address
    - "HR100" - Holding register with 0-based address
    - "C50" - Coil
    - "DI10" - Discrete input
    - "IR200" - Input register
    - "40001.2" - Bit 2 of holding register

    Args:
        address_str: Address string to parse

    Returns:
        ParsedAddress with register type and 0-based address

    Raises:
        ValueError: If address format is invalid
    """
    address_str = address_str.strip().upper()
    bit_offset = None

    # Check for bit access (e.g., "40001.2")
    if "." in address_str:
        base, bit_str = address_str.split(".", 1)
        bit_offset = int(bit_str)
        address_str = base

    # Named prefix format
    if address_str.startswith("HR"):
        return ParsedAddress(
            register_type=ModbusRegisterType.HOLDING_REGISTER,
            address=int(address_str[2:]),
            bit_offset=bit_offset,
        )
    elif address_str.startswith("IR"):
        return ParsedAddress(
            register_type=ModbusRegisterType.INPUT_REGISTER,
            address=int(address_str[2:]),
            bit_offset=bit_offset,
        )
    elif address_str.startswith("DI"):
        return ParsedAddress(
            register_type=ModbusRegisterType.DISCRETE_INPUT,
            address=int(address_str[2:]),
            bit_offset=bit_offset,
        )
    elif address_str.startswith("C"):
        return ParsedAddress(
            register_type=ModbusRegisterType.COIL,
            address=int(address_str[1:]),
            bit_offset=bit_offset,
        )

    # Standard 5-digit Modbus address
    try:
        addr_num = int(address_str)
    except ValueError as e:
        raise ValueError(f"Invalid Modbus address format: {address_str}") from e

    if 1 <= addr_num <= 9999:
        return ParsedAddress(
            register_type=ModbusRegisterType.COIL,
            address=addr_num - 1,
            bit_offset=bit_offset,
        )
    elif 10001 <= addr_num <= 19999:
        return ParsedAddress(
            register_type=ModbusRegisterType.DISCRETE_INPUT,
            address=addr_num - 10001,
            bit_offset=bit_offset,
        )
    elif 30001 <= addr_num <= 39999:
        return ParsedAddress(
            register_type=ModbusRegisterType.INPUT_REGISTER,
            address=addr_num - 30001,
            bit_offset=bit_offset,
        )
    elif 40001 <= addr_num <= 49999:
        return ParsedAddress(
            register_type=ModbusRegisterType.HOLDING_REGISTER,
            address=addr_num - 40001,
            bit_offset=bit_offset,
        )
    else:
        raise ValueError(f"Invalid Modbus address range: {addr_num}")


def decode_registers(
    registers: list[int],
    datatype: str,
    *,
    byte_order: str = "big",
    word_order: str = "big",
) -> float | int | bool:
    """Decode Modbus registers to Python value.

    Args:
        registers: List of 16-bit register values
        datatype: Target data type (int16, uint16, int32, float32, etc.)
        byte_order: Byte order within registers ("big" or "little")
        word_order: Word order across registers ("big" or "little")

    Returns:
        Decoded Python value
    """
    format_map = {
        "bool": (1, "?"),
        "int16": (1, "h"),
        "uint16": (1, "H"),
        "int32": (2, "i"),
        "uint32": (2, "I"),
        "int64": (4, "q"),
        "uint64": (4, "Q"),
        "float32": (2, "f"),
        "float64": (4, "d"),
    }

    if datatype not in format_map:
        raise ValueError(f"Unsupported data type: {datatype}")

    expected_regs, fmt = format_map[datatype]
    if len(registers) < expected_regs:
        raise ValueError(
            f"Not enough registers for {datatype}: got {len(registers)}, need {expected_regs}"
        )

    regs = registers[:expected_regs]
    if word_order == "little" and expected_regs > 1:
        regs = list(reversed(regs))

    raw_bytes = b"".join(r.to_bytes(2, "big") for r in regs)
    if byte_order == "little":
        raw_bytes = b"".join(raw_bytes[i : i + 2][::-1] for i in range(0, len(raw_bytes), 2))

    if datatype == "bool":
        return bool(regs[0] & 0x01)

    return struct.unpack(f">{fmt}", raw_bytes[: expected_regs * 2])[0]


def encode_value(
    value: float | int | bool,
    datatype: str,
    *,
    byte_order: str = "big",
    word_order: str = "big",
) -> list[int]:
    """Encode Python value to Modbus registers.

    Args:
        value: Value to encode
        datatype: Source data type
        byte_order: Byte order

    Returns:
        List of 16-bit register values
    """
    format_map = {
        "bool": "H",
        "int16": "h",
        "uint16": "H",
        "int32": "i",
        "uint32": "I",
        "int64": "q",
        "uint64": "Q",
        "float32": "f",
        "float64": "d",
    }

    if datatype not in format_map:
        raise ValueError(f"Unsupported data type: {datatype}")

    fmt = format_map[datatype]
    raw_bytes = struct.pack(f">{fmt}", value)

    if datatype == "bool":
        raw_bytes = raw_bytes[:2]

    # Split into 16-bit words
    words = [raw_bytes[i : i + 2] for i in range(0, len(raw_bytes), 2)]
    if byte_order == "little":
        words = [word[::-1] for word in words]
    if word_order == "little" and len(words) > 1:
        words = list(reversed(words))

    return [int.from_bytes(word, "big") for word in words]


def get_register_count(datatype: str) -> int:
    """Get number of 16-bit registers needed for a data type."""
    sizes = {
        "bool": 1,
        "int16": 1,
        "uint16": 1,
        "int32": 2,
        "uint32": 2,
        "int64": 4,
        "uint64": 4,
        "float32": 2,
        "float64": 4,
        "string": 1,  # Variable, handled separately
    }
    return sizes.get(datatype, 1)


class ModbusTCPConnector(BaseConnector):
    """Modbus TCP connector implementation."""

    def __init__(self, config: ModbusTCPConnectorConfig) -> None:
        super().__init__(config)
        self._client: AsyncModbusTcpClient | None = None
        self._host = config.host
        self._port = config.port
        self._unit_id = config.unit_id
        self._timeout = config.timeout_ms / 1000

    async def _do_connect(self) -> None:
        """Establish Modbus TCP connection."""
        self._client = AsyncModbusTcpClient(
            host=self._host,
            port=self._port,
            timeout=self._timeout,
        )
        connected = await self._client.connect()
        if not connected:
            raise ConnectionError(f"Failed to connect to {self._host}:{self._port}")

        logger.debug(
            "Modbus TCP connected",
            host=self._host,
            port=self._port,
            unit_id=self._unit_id,
        )

    async def _do_disconnect(self) -> None:
        """Close Modbus TCP connection."""
        if self._client:
            self._client.close()
            self._client = None

    async def _do_read(self, addresses: list[str]) -> dict[str, Any]:
        """Read multiple Modbus addresses.

        Currently reads each address individually. Future optimization:
        coalesce adjacent addresses into single reads.
        """
        if not self._client:
            raise ConnectionError("Not connected")

        results: dict[str, Any] = {}

        for addr_str in addresses:
            try:
                parsed = parse_modbus_address(addr_str)
                value = await self._read_single(parsed)
                results[addr_str] = value
            except Exception as e:
                logger.warning(
                    "Failed to read address",
                    address=addr_str,
                    error=str(e),
                )
                # Don't include failed reads - let caller handle quality

        return results

    async def read_tag_values(self, tags: list["TagDefinition"]) -> dict[str, "TagValue"]:
        """Read Modbus tags using datatype metadata."""
        from mtp_gateway.domain.model.tags import Quality, TagValue

        if not tags:
            return {}

        self._health.total_reads += len(tags)

        if not self._client:
            now = datetime.now(timezone.utc)
            self._health.record_error("Not connected")
            return {
                tag.name: TagValue(
                    value=0,
                    timestamp=now,
                    quality=Quality.BAD_NO_COMMUNICATION,
                )
                for tag in tags
            }

        results: dict[str, TagValue] = {}
        now = datetime.now(timezone.utc)

        for tag in tags:
            try:
                parsed = parse_modbus_address(tag.address)
                value = await self._read_single(
                    parsed,
                    datatype=tag.datatype.value,
                    byte_order=tag.byte_order,
                    word_order=tag.word_order,
                )
                results[tag.name] = TagValue(
                    value=value,
                    timestamp=now,
                    quality=Quality.GOOD,
                )
                self._health.record_success()
            except ValueError as e:
                self._health.record_error(str(e))
                results[tag.name] = TagValue(
                    value=0,
                    timestamp=now,
                    quality=Quality.BAD_CONFIG_ERROR,
                )
            except Exception as e:
                self._health.record_error(str(e))
                results[tag.name] = TagValue(
                    value=0,
                    timestamp=now,
                    quality=Quality.BAD_NO_COMMUNICATION,
                )

        return results

    async def _read_single(
        self,
        parsed: ParsedAddress,
        datatype: str = "uint16",
        *,
        byte_order: str = "big",
        word_order: str = "big",
    ) -> Any:
        """Read a single Modbus address."""
        if not self._client:
            raise ConnectionError("Not connected")

        count = get_register_count(datatype)

        if parsed.register_type == ModbusRegisterType.COIL:
            response = await self._client.read_coils(
                address=parsed.address,
                count=1,
                slave=self._unit_id,
            )
            if isinstance(response, ExceptionResponse):
                raise ModbusException(f"Modbus exception: {response}")
            return response.bits[0]

        elif parsed.register_type == ModbusRegisterType.DISCRETE_INPUT:
            response = await self._client.read_discrete_inputs(
                address=parsed.address,
                count=1,
                slave=self._unit_id,
            )
            if isinstance(response, ExceptionResponse):
                raise ModbusException(f"Modbus exception: {response}")
            return response.bits[0]

        elif parsed.register_type == ModbusRegisterType.INPUT_REGISTER:
            response = await self._client.read_input_registers(
                address=parsed.address,
                count=count,
                slave=self._unit_id,
            )
            if isinstance(response, ExceptionResponse):
                raise ModbusException(f"Modbus exception: {response}")
            if parsed.bit_offset is not None:
                return bool((response.registers[0] >> parsed.bit_offset) & 0x01)
            return decode_registers(
                response.registers,
                datatype,
                byte_order=byte_order,
                word_order=word_order,
            )

        elif parsed.register_type == ModbusRegisterType.HOLDING_REGISTER:
            response = await self._client.read_holding_registers(
                address=parsed.address,
                count=count,
                slave=self._unit_id,
            )
            if isinstance(response, ExceptionResponse):
                raise ModbusException(f"Modbus exception: {response}")
            if parsed.bit_offset is not None:
                return bool((response.registers[0] >> parsed.bit_offset) & 0x01)
            return decode_registers(
                response.registers,
                datatype,
                byte_order=byte_order,
                word_order=word_order,
            )

        raise ValueError(f"Unknown register type: {parsed.register_type}")

    async def _do_write(self, address: str, value: Any) -> None:
        """Write to a single Modbus address."""
        if not self._client:
            raise ConnectionError("Not connected")

        parsed = parse_modbus_address(address)

        if parsed.register_type == ModbusRegisterType.COIL:
            response = await self._client.write_coil(
                address=parsed.address,
                value=bool(value),
                slave=self._unit_id,
            )
        elif parsed.register_type == ModbusRegisterType.HOLDING_REGISTER:
            # Determine if single or multiple register write
            if isinstance(value, bool):
                registers = [1 if value else 0]
            elif isinstance(value, int):
                registers = encode_value(value, "int16")
            elif isinstance(value, float):
                registers = encode_value(value, "float32")
            else:
                raise ValueError(f"Unsupported write value type: {type(value)}")

            if len(registers) == 1:
                response = await self._client.write_register(
                    address=parsed.address,
                    value=registers[0],
                    slave=self._unit_id,
                )
            else:
                response = await self._client.write_registers(
                    address=parsed.address,
                    values=registers,
                    slave=self._unit_id,
                )
        else:
            raise ValueError(f"Cannot write to {parsed.register_type.value}")

        if isinstance(response, ExceptionResponse):
            raise ModbusException(f"Write failed: {response}")

    async def write_tag_value(self, tag: "TagDefinition", value: Any) -> bool:
        """Write a Modbus tag using datatype metadata."""
        self._health.total_writes += 1

        if not self._client:
            self._health.record_error("Not connected")
            return False

        try:
            parsed = parse_modbus_address(tag.address)
            if parsed.register_type == ModbusRegisterType.COIL:
                response = await self._client.write_coil(
                    address=parsed.address,
                    value=bool(value),
                    slave=self._unit_id,
                )
            elif parsed.register_type == ModbusRegisterType.HOLDING_REGISTER:
                if parsed.bit_offset is not None:
                    raise ValueError("Bit-level writes to registers are not supported")

                registers = encode_value(
                    value,
                    tag.datatype.value,
                    byte_order=tag.byte_order,
                    word_order=tag.word_order,
                )

                if len(registers) == 1:
                    response = await self._client.write_register(
                        address=parsed.address,
                        value=registers[0],
                        slave=self._unit_id,
                    )
                else:
                    response = await self._client.write_registers(
                        address=parsed.address,
                        values=registers,
                        slave=self._unit_id,
                    )
            else:
                raise ValueError(f"Cannot write to {parsed.register_type.value}")

            if isinstance(response, ExceptionResponse):
                raise ModbusException(f"Write failed: {response}")

            self._health.record_success()
            return True
        except Exception as e:
            self._health.record_error(str(e))
            logger.error(
                "Write failed",
                connector=self.name,
                address=tag.address,
                error=str(e),
            )
            return False


class ModbusRTUConnector(BaseConnector):
    """Modbus RTU (serial) connector implementation."""

    def __init__(self, config: ModbusRTUConnectorConfig) -> None:
        super().__init__(config)
        self._client: AsyncModbusSerialClient | None = None
        self._port = config.port
        self._baudrate = config.baudrate
        self._parity = config.parity
        self._stopbits = config.stopbits
        self._bytesize = config.bytesize
        self._unit_id = config.unit_id
        self._timeout = config.timeout_ms / 1000

    async def _do_connect(self) -> None:
        """Establish Modbus RTU connection."""
        self._client = AsyncModbusSerialClient(
            port=self._port,
            baudrate=self._baudrate,
            parity=self._parity,
            stopbits=self._stopbits,
            bytesize=self._bytesize,
            timeout=self._timeout,
        )
        connected = await self._client.connect()
        if not connected:
            raise ConnectionError(f"Failed to connect to serial port {self._port}")

        logger.debug(
            "Modbus RTU connected",
            port=self._port,
            baudrate=self._baudrate,
        )

    async def _do_disconnect(self) -> None:
        """Close Modbus RTU connection."""
        if self._client:
            self._client.close()
            self._client = None

    async def _do_read(self, addresses: list[str]) -> dict[str, Any]:
        """Read multiple Modbus addresses (RTU)."""
        # Same implementation as TCP, just different client
        if not self._client:
            raise ConnectionError("Not connected")

        results: dict[str, Any] = {}

        for addr_str in addresses:
            try:
                parsed = parse_modbus_address(addr_str)
                value = await self._read_single_rtu(parsed)
                results[addr_str] = value
            except Exception as e:
                logger.warning(
                    "Failed to read address",
                    address=addr_str,
                    error=str(e),
                )

        return results

    async def read_tag_values(self, tags: list["TagDefinition"]) -> dict[str, "TagValue"]:
        """Read Modbus RTU tags using datatype metadata."""
        from mtp_gateway.domain.model.tags import Quality, TagValue

        if not tags:
            return {}

        self._health.total_reads += len(tags)

        if not self._client:
            now = datetime.now(timezone.utc)
            self._health.record_error("Not connected")
            return {
                tag.name: TagValue(
                    value=0,
                    timestamp=now,
                    quality=Quality.BAD_NO_COMMUNICATION,
                )
                for tag in tags
            }

        results: dict[str, TagValue] = {}
        now = datetime.now(timezone.utc)

        for tag in tags:
            try:
                parsed = parse_modbus_address(tag.address)
                value = await self._read_single_rtu(
                    parsed,
                    datatype=tag.datatype.value,
                    byte_order=tag.byte_order,
                    word_order=tag.word_order,
                )
                results[tag.name] = TagValue(
                    value=value,
                    timestamp=now,
                    quality=Quality.GOOD,
                )
                self._health.record_success()
            except ValueError as e:
                self._health.record_error(str(e))
                results[tag.name] = TagValue(
                    value=0,
                    timestamp=now,
                    quality=Quality.BAD_CONFIG_ERROR,
                )
            except Exception as e:
                self._health.record_error(str(e))
                results[tag.name] = TagValue(
                    value=0,
                    timestamp=now,
                    quality=Quality.BAD_NO_COMMUNICATION,
                )

        return results

    async def _read_single_rtu(
        self,
        parsed: ParsedAddress,
        datatype: str = "uint16",
        *,
        byte_order: str = "big",
        word_order: str = "big",
    ) -> Any:
        """Read a single Modbus RTU address."""
        if not self._client:
            raise ConnectionError("Not connected")

        count = get_register_count(datatype)

        if parsed.register_type == ModbusRegisterType.COIL:
            response = await self._client.read_coils(
                address=parsed.address,
                count=1,
                slave=self._unit_id,
            )
            if isinstance(response, ExceptionResponse):
                raise ModbusException(f"Modbus exception: {response}")
            return response.bits[0]

        elif parsed.register_type == ModbusRegisterType.DISCRETE_INPUT:
            response = await self._client.read_discrete_inputs(
                address=parsed.address,
                count=1,
                slave=self._unit_id,
            )
            if isinstance(response, ExceptionResponse):
                raise ModbusException(f"Modbus exception: {response}")
            return response.bits[0]

        elif parsed.register_type == ModbusRegisterType.INPUT_REGISTER:
            response = await self._client.read_input_registers(
                address=parsed.address,
                count=count,
                slave=self._unit_id,
            )
            if isinstance(response, ExceptionResponse):
                raise ModbusException(f"Modbus exception: {response}")
            if parsed.bit_offset is not None:
                return bool((response.registers[0] >> parsed.bit_offset) & 0x01)
            return decode_registers(
                response.registers,
                datatype,
                byte_order=byte_order,
                word_order=word_order,
            )

        elif parsed.register_type == ModbusRegisterType.HOLDING_REGISTER:
            response = await self._client.read_holding_registers(
                address=parsed.address,
                count=count,
                slave=self._unit_id,
            )
            if isinstance(response, ExceptionResponse):
                raise ModbusException(f"Modbus exception: {response}")
            if parsed.bit_offset is not None:
                return bool((response.registers[0] >> parsed.bit_offset) & 0x01)
            return decode_registers(
                response.registers,
                datatype,
                byte_order=byte_order,
                word_order=word_order,
            )

        raise ValueError(f"Unknown register type: {parsed.register_type}")

    async def _do_write(self, address: str, value: Any) -> None:
        """Write to a single Modbus RTU address."""
        if not self._client:
            raise ConnectionError("Not connected")

        parsed = parse_modbus_address(address)

        if parsed.register_type == ModbusRegisterType.COIL:
            response = await self._client.write_coil(
                address=parsed.address,
                value=bool(value),
                slave=self._unit_id,
            )
        elif parsed.register_type == ModbusRegisterType.HOLDING_REGISTER:
            if isinstance(value, bool):
                registers = [1 if value else 0]
            elif isinstance(value, int):
                registers = encode_value(value, "int16")
            elif isinstance(value, float):
                registers = encode_value(value, "float32")
            else:
                raise ValueError(f"Unsupported write value type: {type(value)}")

            if len(registers) == 1:
                response = await self._client.write_register(
                    address=parsed.address,
                    value=registers[0],
                    slave=self._unit_id,
                )
            else:
                response = await self._client.write_registers(
                    address=parsed.address,
                    values=registers,
                    slave=self._unit_id,
                )
        else:
            raise ValueError(f"Cannot write to {parsed.register_type.value}")

        if isinstance(response, ExceptionResponse):
            raise ModbusException(f"Write failed: {response}")

    async def write_tag_value(self, tag: "TagDefinition", value: Any) -> bool:
        """Write a Modbus RTU tag using datatype metadata."""
        self._health.total_writes += 1

        if not self._client:
            self._health.record_error("Not connected")
            return False

        try:
            parsed = parse_modbus_address(tag.address)
            if parsed.register_type == ModbusRegisterType.COIL:
                response = await self._client.write_coil(
                    address=parsed.address,
                    value=bool(value),
                    slave=self._unit_id,
                )
            elif parsed.register_type == ModbusRegisterType.HOLDING_REGISTER:
                if parsed.bit_offset is not None:
                    raise ValueError("Bit-level writes to registers are not supported")

                registers = encode_value(
                    value,
                    tag.datatype.value,
                    byte_order=tag.byte_order,
                    word_order=tag.word_order,
                )

                if len(registers) == 1:
                    response = await self._client.write_register(
                        address=parsed.address,
                        value=registers[0],
                        slave=self._unit_id,
                    )
                else:
                    response = await self._client.write_registers(
                        address=parsed.address,
                        values=registers,
                        slave=self._unit_id,
                    )
            else:
                raise ValueError(f"Cannot write to {parsed.register_type.value}")

            if isinstance(response, ExceptionResponse):
                raise ModbusException(f"Write failed: {response}")

            self._health.record_success()
            return True
        except Exception as e:
            self._health.record_error(str(e))
            logger.error(
                "Write failed",
                connector=self.name,
                address=tag.address,
                error=str(e),
            )
            return False
