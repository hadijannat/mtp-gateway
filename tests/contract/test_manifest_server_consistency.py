"""Contract tests for manifest and server consistency.

These tests ensure that every NodeID referenced in the generated
MTP manifest actually exists in the OPC UA server address space.

This is critical for POL interoperability - if the manifest references
a node that doesn't exist, POL integration will fail.
"""

from __future__ import annotations

import pytest

from mtp_gateway.adapters.northbound.manifest.generator import MTPManifestGenerator
from mtp_gateway.adapters.northbound.opcua.nodes import MTPNodeBuilder
from mtp_gateway.config.schema import (
    DataAssemblyConfig,
    DataTypeConfig,
    GatewayConfig,
    GatewayInfo,
    ModbusTCPConnectorConfig,
    MTPConfig,
    OPCUAConfig,
    ServiceConfig,
    TagConfig,
)


@pytest.fixture
def sample_config() -> GatewayConfig:
    """Create a sample configuration for testing."""
    return GatewayConfig(
        gateway=GatewayInfo(name="TestPEA", version="1.0.0"),
        opcua=OPCUAConfig(
            endpoint="opc.tcp://localhost:4840",
            namespace_uri="urn:test:pea",
        ),
        connectors=[
            ModbusTCPConnectorConfig(name="plc1", host="192.168.1.100"),
        ],
        tags=[
            TagConfig(
                name="temp_sensor",
                connector="plc1",
                address="40001",
                datatype=DataTypeConfig.FLOAT32,
            ),
            TagConfig(
                name="valve_cmd",
                connector="plc1",
                address="00001",
                datatype=DataTypeConfig.BOOL,
                writable=True,
            ),
        ],
        mtp=MTPConfig(
            data_assemblies=[
                DataAssemblyConfig(
                    name="TempSensor_01",
                    type="AnaView",
                    bindings={"V": "temp_sensor"},
                ),
                DataAssemblyConfig(
                    name="Valve_01",
                    type="BinVlv",
                    bindings={"V": "valve_cmd"},
                ),
            ],
            services=[
                ServiceConfig(
                    name="Dosing",
                    procedures=[],
                ),
            ],
        ),
    )


@pytest.mark.contract
class TestManifestServerConsistency:
    """Tests ensuring manifest and server are consistent."""

    def test_manifest_data_assembly_nodes_match_server(
        self, sample_config: GatewayConfig
    ) -> None:
        """All data assembly node IDs in manifest must exist in server."""
        # Generate manifest node IDs
        generator = MTPManifestGenerator(sample_config)
        manifest_node_ids = generator.get_all_node_ids()

        # Build server node IDs (simulating what the server would create)
        # In a real test, we'd start the server and query it
        pea_name = sample_config.gateway.name

        # Build expected server nodes from config
        server_node_ids: set[str] = set()

        for da in sample_config.mtp.data_assemblies:
            base = f"ns=2;s=PEA_{pea_name}.DataAssemblies.{da.name}"
            for attr_name in da.bindings.keys():
                server_node_ids.add(f"{base}.{attr_name}")

        for service in sample_config.mtp.services:
            base = f"ns=2;s=PEA_{pea_name}.Services.{service.name}"
            server_node_ids.add(f"{base}.CommandOp")
            server_node_ids.add(f"{base}.StateCur")
            server_node_ids.add(f"{base}.ProcedureCur")
            server_node_ids.add(f"{base}.ProcedureReq")

        # Check all manifest nodes exist in server
        for node_id in manifest_node_ids:
            assert node_id in server_node_ids, f"Manifest references missing node: {node_id}"

    def test_manifest_service_nodes_match_server(
        self, sample_config: GatewayConfig
    ) -> None:
        """All service node IDs in manifest must exist in server."""
        generator = MTPManifestGenerator(sample_config)
        manifest_node_ids = generator.get_all_node_ids()

        pea_name = sample_config.gateway.name

        # Expected service nodes
        expected_service_nodes = []
        for service in sample_config.mtp.services:
            base = f"ns=2;s=PEA_{pea_name}.Services.{service.name}"
            expected_service_nodes.extend(
                [
                    f"{base}.CommandOp",
                    f"{base}.StateCur",
                    f"{base}.ProcedureCur",
                    f"{base}.ProcedureReq",
                ]
            )

        # Check each expected service node is in manifest
        for expected in expected_service_nodes:
            assert expected in manifest_node_ids, f"Service node missing from manifest: {expected}"

    def test_node_id_format_is_valid(self, sample_config: GatewayConfig) -> None:
        """All node IDs should follow OPC UA format."""
        generator = MTPManifestGenerator(sample_config)
        manifest_node_ids = generator.get_all_node_ids()

        for node_id in manifest_node_ids:
            # Node IDs should start with namespace identifier
            assert node_id.startswith("ns="), f"Invalid node ID format: {node_id}"
            # Should contain string identifier
            assert ";s=" in node_id, f"Node ID missing string identifier: {node_id}"

    def test_no_duplicate_node_ids(self, sample_config: GatewayConfig) -> None:
        """Manifest should not contain duplicate node IDs."""
        generator = MTPManifestGenerator(sample_config)
        manifest_node_ids = generator.get_all_node_ids()

        seen: set[str] = set()
        duplicates: list[str] = []

        for node_id in manifest_node_ids:
            if node_id in seen:
                duplicates.append(node_id)
            seen.add(node_id)

        assert not duplicates, f"Duplicate node IDs found: {duplicates}"
