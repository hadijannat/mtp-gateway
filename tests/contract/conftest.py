"""Contract test fixtures for live OPC UA server testing.

These fixtures enable verification that every NodeID referenced in the
generated MTP manifest actually exists in the live OPC UA server address space.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, AsyncGenerator

import pytest
from asyncua import Client

from mtp_gateway.adapters.northbound.manifest.generator import MTPManifestGenerator
from mtp_gateway.adapters.northbound.opcua.server import MTPOPCUAServer
from mtp_gateway.application.tag_manager import TagManager
from mtp_gateway.config.schema import (
    DataAssemblyConfig,
    DataTypeConfig,
    GatewayConfig,
    GatewayInfo,
    ModbusTCPConnectorConfig,
    MTPConfig,
    OPCUAConfig,
    OPCUASecurityConfig,
    ProcedureConfig,
    ProxyMode,
    ServiceConfig,
    TagConfig,
)

if TYPE_CHECKING:
    from asyncua import Node


# Auto-mark all tests in this package as contract tests
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Auto-mark tests in contract directory with contract marker."""
    for item in items:
        if "contract" in str(item.fspath):
            item.add_marker(pytest.mark.contract)


@pytest.fixture
def contract_config() -> GatewayConfig:
    """Create a comprehensive configuration for contract testing.

    This config includes:
    - Multiple data assembly types (AnaView, BinVlv, AnaMon)
    - Multiple services with different proxy modes
    - Procedures and parameters
    """
    return GatewayConfig(
        gateway=GatewayInfo(
            name="ContractTestPEA",
            version="1.0.0",
            description="PEA for contract testing",
        ),
        opcua=OPCUAConfig(
            endpoint="opc.tcp://127.0.0.1:48401",  # Non-standard port for tests
            namespace_uri="urn:contract-test:pea",
            application_name="Contract Test Server",
            security=OPCUASecurityConfig(allow_none=True, policies=[]),
        ),
        connectors=[
            ModbusTCPConnectorConfig(name="test_plc", host="127.0.0.1"),
        ],
        tags=[
            # Analog tags
            TagConfig(name="temp_pv", connector="test_plc", address="40001", datatype=DataTypeConfig.FLOAT32),
            TagConfig(name="temp_sp", connector="test_plc", address="40003", datatype=DataTypeConfig.FLOAT32, writable=True),
            TagConfig(name="pressure_pv", connector="test_plc", address="40005", datatype=DataTypeConfig.FLOAT32),
            # Binary tags
            TagConfig(name="valve_cmd", connector="test_plc", address="00001", datatype=DataTypeConfig.BOOL, writable=True),
            TagConfig(name="valve_fbk", connector="test_plc", address="10001", datatype=DataTypeConfig.BOOL),
            TagConfig(name="pump_run", connector="test_plc", address="00002", datatype=DataTypeConfig.BOOL, writable=True),
            # Service state tags
            TagConfig(name="dosing_state", connector="test_plc", address="40010", datatype=DataTypeConfig.UINT32),
            TagConfig(name="dosing_cmd", connector="test_plc", address="40011", datatype=DataTypeConfig.UINT32, writable=True),
        ],
        mtp=MTPConfig(
            data_assemblies=[
                DataAssemblyConfig(
                    name="TempSensor_01",
                    type="AnaView",
                    bindings={"V": "temp_pv"},
                    description="Temperature sensor",
                    v_scl_min=0.0,
                    v_scl_max=100.0,
                    v_unit=1001,  # °C
                ),
                DataAssemblyConfig(
                    name="TempSetpoint_01",
                    type="AnaServParam",
                    bindings={"V": "temp_sp"},
                    description="Temperature setpoint",
                ),
                DataAssemblyConfig(
                    name="PressureSensor_01",
                    type="AnaMon",
                    bindings={"V": "pressure_pv"},
                    description="Pressure monitoring",
                ),
                DataAssemblyConfig(
                    name="Valve_01",
                    type="BinVlv",
                    bindings={"V": "valve_cmd", "VFbk": "valve_fbk"},
                    description="Binary valve",
                    v_state_0="Closed",
                    v_state_1="Open",
                ),
                DataAssemblyConfig(
                    name="Pump_01",
                    type="BinDrv",
                    bindings={"V": "pump_run"},
                    description="Pump drive",
                ),
            ],
            services=[
                ServiceConfig(
                    name="Dosing",
                    mode=ProxyMode.THICK,
                    procedures=[
                        ProcedureConfig(id=1, name="FastDose", is_default=True),
                        ProcedureConfig(id=2, name="SlowDose"),
                    ],
                ),
                ServiceConfig(
                    name="Heating",
                    mode=ProxyMode.THIN,
                    state_cur_tag="dosing_state",
                    command_op_tag="dosing_cmd",
                ),
            ],
        ),
    )


@pytest.fixture
def tag_manager(contract_config: GatewayConfig) -> TagManager:
    """Create a minimal TagManager for server testing.

    The TagManager doesn't need actual connectors for contract tests -
    we only care about the OPC UA address space structure.
    """
    return TagManager(connectors={}, tags=contract_config.tags)


@pytest.fixture
async def opcua_server(
    contract_config: GatewayConfig,
    tag_manager: TagManager,
) -> AsyncGenerator[MTPOPCUAServer, None]:
    """Start a live OPC UA server for contract testing.

    Yields the running server, then stops it after the test.
    """
    server = MTPOPCUAServer(
        config=contract_config,
        tag_manager=tag_manager,
    )

    await server.start()

    # Give server time to fully initialize
    await asyncio.sleep(0.1)

    try:
        yield server
    finally:
        await server.stop()


@pytest.fixture
async def opcua_client(
    contract_config: GatewayConfig,
    opcua_server: MTPOPCUAServer,
) -> AsyncGenerator[Client, None]:
    """Create an OPC UA client connected to the test server.

    Yields the connected client, then disconnects after the test.
    """
    client = Client(contract_config.opcua.endpoint)

    await client.connect()

    try:
        yield client
    finally:
        await client.disconnect()


@pytest.fixture
def manifest_generator(contract_config: GatewayConfig) -> MTPManifestGenerator:
    """Create a manifest generator for the test configuration."""
    return MTPManifestGenerator(contract_config)


@pytest.fixture
async def server_node_ids(
    opcua_client: Client,
    contract_config: GatewayConfig,
) -> set[str]:
    """Browse the server and collect all node IDs under the PEA.

    Returns a set of expanded node ID strings for all nodes
    in the server's address space under the PEA hierarchy.
    """
    from tests.contract.helpers import OPCUABrowser

    browser = OPCUABrowser(opcua_client, contract_config)
    return await browser.browse_all_node_ids()


@pytest.fixture
async def server_nodes_with_types(
    opcua_client: Client,
    contract_config: GatewayConfig,
) -> dict[str, str]:
    """Browse the server and collect node IDs with their data types.

    Returns a dict mapping expanded node ID strings to their
    OPC UA VariantType names.
    """
    from tests.contract.helpers import OPCUABrowser

    browser = OPCUABrowser(opcua_client, contract_config)
    return await browser.browse_nodes_with_types()
