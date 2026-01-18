"""Unit tests for runtime communication loss handling."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from mtp_gateway.config.schema import (
    CommLossAction,
    GatewayConfig,
    GatewayInfo,
    MTPConfig,
    OPCUAConfig,
    RuntimePolicyConfig,
    SafetyConfig,
)
from mtp_gateway.main import GatewayRuntime


def _config_with_action(action: CommLossAction, *, with_safe_output: bool = False) -> GatewayConfig:
    safe_outputs = []
    allowlist = []
    if with_safe_output:
        safe_outputs = [
            {"tag": "safe_tag", "value": 0},
        ]
        allowlist = ["safe_tag"]
    connectors = []
    tags = []
    if with_safe_output:
        connectors = [
            {
                "type": "modbus_tcp",
                "name": "plc1",
                "host": "127.0.0.1",
            }
        ]
        tags = [
            {
                "name": "safe_tag",
                "connector": "plc1",
                "address": "00001",
                "datatype": "bool",
                "writable": True,
            }
        ]
    return GatewayConfig(
        gateway=GatewayInfo(name="RuntimeTest", version="0.1.0"),
        opcua=OPCUAConfig(endpoint="opc.tcp://localhost:4840", namespace_uri="urn:test"),
        runtime=RuntimePolicyConfig(comm_loss_action=action, comm_loss_grace_s=0),
        connectors=connectors,
        tags=tags,
        mtp=MTPConfig(),
        safety=SafetyConfig(
            write_allowlist=allowlist,
            safe_state_outputs=safe_outputs,
            command_rate_limit="10/s",
        ),
    )


@pytest.mark.asyncio
async def test_comm_loss_safe_state_triggers_tag_writes() -> None:
    config = _config_with_action(CommLossAction.SAFE_STATE, with_safe_output=True)
    runtime = GatewayRuntime(config)

    tag_manager = MagicMock()
    tag_manager.write_tag = AsyncMock(return_value=True)
    runtime._tag_manager = tag_manager  # intentional for unit test

    await runtime._handle_comm_loss("plc1", CommLossAction.SAFE_STATE)

    tag_manager.write_tag.assert_called_once_with("safe_tag", 0)


@pytest.mark.asyncio
async def test_comm_loss_abort_services_triggers_emergency_stop() -> None:
    config = _config_with_action(CommLossAction.ABORT_SERVICES)
    runtime = GatewayRuntime(config)

    service_manager = MagicMock()
    service_manager.emergency_stop = AsyncMock()
    runtime._service_manager = service_manager  # intentional for unit test

    await runtime._handle_comm_loss("plc1", CommLossAction.ABORT_SERVICES)

    service_manager.emergency_stop.assert_called_once()
