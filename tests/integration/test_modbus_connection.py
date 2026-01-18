from __future__ import annotations

import os
import socket

import pytest

from mtp_gateway.config.schema import ModbusTCPConnectorConfig

_PYMODBUS_AVAILABLE = True
try:
    from mtp_gateway.adapters.southbound.modbus.driver import ModbusTCPConnector
except ModuleNotFoundError:
    _PYMODBUS_AVAILABLE = False


def _modbus_reachable(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


@pytest.mark.asyncio
async def test_modbus_tcp_connects_and_disconnects() -> None:
    if not _PYMODBUS_AVAILABLE:
        pytest.skip("pymodbus not installed")

    host = os.getenv("MTP_MODBUS_HOST", "127.0.0.1")
    port = int(os.getenv("MTP_MODBUS_PORT", "5020"))

    if not _modbus_reachable(host, port):
        pytest.skip(f"Modbus simulator not reachable at {host}:{port}")

    config = ModbusTCPConnectorConfig(
        name="modbus-integration",
        host=host,
        port=port,
        unit_id=1,
        timeout_ms=1000,
        retry_count=1,
        retry_delay_ms=100,
    )

    connector = ModbusTCPConnector(config)
    await connector.connect()
    await connector.disconnect()
