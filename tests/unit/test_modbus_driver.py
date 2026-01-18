from __future__ import annotations

from dataclasses import dataclass

import pytest

from mtp_gateway.adapters.southbound.modbus.driver import (
    ModbusRegisterType,
    ModbusTCPConnector,
    ParsedAddress,
    decode_registers,
    encode_value,
    parse_modbus_address,
)
from mtp_gateway.config.schema import ModbusTCPConnectorConfig
from mtp_gateway.domain.model.tags import DataType, TagDefinition, TagValue, Quality


@dataclass
class DummyResponse:
    bits: list[bool] | None = None
    registers: list[int] | None = None


class DummyClient:
    def __init__(self) -> None:
        self.last_write: tuple[str, int, object] | None = None

    async def read_coils(self, address: int, count: int = 1, **_kwargs: object) -> DummyResponse:
        return DummyResponse(bits=[True])

    async def read_discrete_inputs(
        self, address: int, count: int = 1, **_kwargs: object
    ) -> DummyResponse:
        return DummyResponse(bits=[False])

    async def read_input_registers(
        self, address: int, count: int = 1, **_kwargs: object
    ) -> DummyResponse:
        return DummyResponse(registers=[8])

    async def read_holding_registers(
        self, address: int, count: int = 1, **_kwargs: object
    ) -> DummyResponse:
        return DummyResponse(registers=[42])

    async def write_coil(self, address: int, value: bool, **_kwargs: object) -> DummyResponse:
        self.last_write = ("coil", address, value)
        return DummyResponse()

    async def write_register(self, address: int, value: int, **_kwargs: object) -> DummyResponse:
        self.last_write = ("register", address, value)
        return DummyResponse()

    async def write_registers(
        self, address: int, values: list[int], **_kwargs: object
    ) -> DummyResponse:
        self.last_write = ("registers", address, list(values))
        return DummyResponse()


def make_tcp_connector() -> ModbusTCPConnector:
    config = ModbusTCPConnectorConfig(name="modbus", host="127.0.0.1")
    connector = ModbusTCPConnector(config)
    connector._client = DummyClient()
    return connector


def test_parse_modbus_address_ranges() -> None:
    assert parse_modbus_address("1") == ParsedAddress(
        register_type=ModbusRegisterType.COIL,
        address=0,
        bit_offset=None,
    )
    assert parse_modbus_address("10001") == ParsedAddress(
        register_type=ModbusRegisterType.DISCRETE_INPUT,
        address=0,
        bit_offset=None,
    )
    assert parse_modbus_address("30001") == ParsedAddress(
        register_type=ModbusRegisterType.INPUT_REGISTER,
        address=0,
        bit_offset=None,
    )
    assert parse_modbus_address("40001") == ParsedAddress(
        register_type=ModbusRegisterType.HOLDING_REGISTER,
        address=0,
        bit_offset=None,
    )


def test_parse_modbus_address_bit_offset() -> None:
    parsed = parse_modbus_address("40001.3")
    assert parsed.register_type == ModbusRegisterType.HOLDING_REGISTER
    assert parsed.address == 0
    assert parsed.bit_offset == 3


def test_encode_decode_roundtrip_float32() -> None:
    value = 12.5
    registers = encode_value(value, "float32")
    decoded = decode_registers(registers, "float32")
    assert decoded == pytest.approx(value)


@pytest.mark.asyncio
async def test_read_tag_values_not_connected() -> None:
    config = ModbusTCPConnectorConfig(name="modbus", host="127.0.0.1")
    connector = ModbusTCPConnector(config)

    tag = TagDefinition(
        name="temp",
        connector="modbus",
        address="40001",
        datatype=DataType.UINT16,
    )
    results = await connector.read_tag_values([tag])

    assert results["temp"].quality == Quality.BAD_NO_COMMUNICATION


@pytest.mark.asyncio
async def test_read_single_holding_register() -> None:
    connector = make_tcp_connector()
    parsed = ParsedAddress(register_type=ModbusRegisterType.HOLDING_REGISTER, address=0)

    value = await connector._read_single(parsed, datatype="uint16")
    assert value == 42


@pytest.mark.asyncio
async def test_read_single_bit_offset() -> None:
    connector = make_tcp_connector()
    parsed = ParsedAddress(
        register_type=ModbusRegisterType.INPUT_REGISTER,
        address=0,
        bit_offset=3,
    )

    value = await connector._read_single(parsed, datatype="uint16")
    assert value is True


@pytest.mark.asyncio
async def test_write_tag_value_coil() -> None:
    connector = make_tcp_connector()
    tag = TagDefinition(
        name="coil",
        connector="modbus",
        address="1",
        datatype=DataType.BOOL,
        writable=True,
    )

    success = await connector.write_tag_value(tag, True)
    assert success is True


@pytest.mark.asyncio
async def test_write_tag_value_register_float32() -> None:
    connector = make_tcp_connector()
    tag = TagDefinition(
        name="register",
        connector="modbus",
        address="40001",
        datatype=DataType.FLOAT32,
        writable=True,
    )

    success = await connector.write_tag_value(tag, 3.14)
    assert success is True
