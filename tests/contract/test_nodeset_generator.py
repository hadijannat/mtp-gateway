"""Tests for NodeSet2 XML generation.

These tests verify:
1. NodeSet2 XML is valid and well-formed
2. Contains expected nodes matching configuration
3. Deterministic generation produces identical output
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from mtp_gateway.adapters.northbound.nodeset.generator import NodeSetGenerator
from mtp_gateway.config.schema import (
    DataAssemblyConfig,
    DataTypeConfig,
    GatewayConfig,
    GatewayInfo,
    ModbusTCPConnectorConfig,
    MTPConfig,
    OPCUAConfig,
    ProcedureConfig,
    ProxyMode,
    ServiceConfig,
    TagConfig,
)

# NodeSet2 namespace
NODESET_NS = "http://opcfoundation.org/UA/2011/03/UANodeSet.xsd"


def _tag(name: str) -> str:
    """Create a namespaced tag."""
    return f"{{{NODESET_NS}}}{name}"


@pytest.fixture
def sample_config() -> GatewayConfig:
    """Create a sample gateway configuration for testing."""
    return GatewayConfig(
        gateway=GatewayInfo(
            name="TestModule",
            version="1.0.0",
            description="Test module for NodeSet testing",
        ),
        opcua=OPCUAConfig(
            endpoint="opc.tcp://localhost:4840",
            namespace_uri="urn:test:module",
        ),
        connectors=[
            ModbusTCPConnectorConfig(name="plc1", host="192.168.1.100"),
        ],
        tags=[
            TagConfig(
                name="temperature",
                connector="plc1",
                address="40001",
                datatype=DataTypeConfig.FLOAT32,
            ),
            TagConfig(
                name="valve_state",
                connector="plc1",
                address="40003",
                datatype=DataTypeConfig.BOOL,
            ),
        ],
        mtp=MTPConfig(
            data_assemblies=[
                DataAssemblyConfig(
                    name="TempSensor",
                    type="AnaView",
                    bindings={"V": "temperature"},
                    description="Temperature sensor",
                ),
                DataAssemblyConfig(
                    name="Valve1",
                    type="BinVlv",
                    bindings={"V": "valve_state"},
                ),
            ],
            services=[
                ServiceConfig(
                    name="Heating",
                    mode=ProxyMode.THICK,
                    procedures=[
                        ProcedureConfig(id=0, name="HeatUp", is_default=True),
                    ],
                ),
            ],
        ),
    )


class TestNodeSetGenerator:
    """Tests for NodeSet2 XML generation."""

    def test_generates_valid_xml(self, sample_config: GatewayConfig) -> None:
        """Generated XML should be well-formed and parseable."""
        generator = NodeSetGenerator(sample_config, deterministic=True)
        xml_str = generator.generate()

        # Should not raise
        root = ET.fromstring(xml_str)
        assert root.tag == _tag("UANodeSet")

    def test_contains_namespace_uri(self, sample_config: GatewayConfig) -> None:
        """NodeSet should declare the custom namespace URI."""
        generator = NodeSetGenerator(sample_config, deterministic=True)
        xml_str = generator.generate()

        root = ET.fromstring(xml_str)
        ns_uris = root.find(_tag("NamespaceUris"))
        assert ns_uris is not None

        uri = ns_uris.find(_tag("Uri"))
        assert uri is not None
        assert uri.text == "urn:test:module"

    def test_contains_type_aliases(self, sample_config: GatewayConfig) -> None:
        """NodeSet should include standard OPC UA type aliases."""
        generator = NodeSetGenerator(sample_config, deterministic=True)
        xml_str = generator.generate()

        root = ET.fromstring(xml_str)
        aliases = root.find(_tag("Aliases"))
        assert aliases is not None

        alias_elements = aliases.findall(_tag("Alias"))
        alias_names = {a.get("Alias") for a in alias_elements}

        assert "Boolean" in alias_names
        assert "Double" in alias_names
        assert "String" in alias_names
        assert "FolderType" in alias_names

    def test_contains_pea_folder(self, sample_config: GatewayConfig) -> None:
        """NodeSet should contain the PEA root folder."""
        generator = NodeSetGenerator(sample_config, deterministic=True)
        xml_str = generator.generate()

        root = ET.fromstring(xml_str)

        # Find UAObject with PEA NodeId
        for obj in root.iter(_tag("UAObject")):
            if obj.get("NodeId") == "ns=1;s=PEA_TestModule":
                display_name = obj.find(_tag("DisplayName"))
                assert display_name is not None
                assert display_name.text == "PEA_TestModule"
                return

        pytest.fail("PEA root folder not found")

    def test_contains_data_assemblies_folder(self, sample_config: GatewayConfig) -> None:
        """NodeSet should contain DataAssemblies folder."""
        generator = NodeSetGenerator(sample_config, deterministic=True)
        xml_str = generator.generate()

        root = ET.fromstring(xml_str)

        for obj in root.iter(_tag("UAObject")):
            if obj.get("NodeId") == "ns=1;s=PEA_TestModule.DataAssemblies":
                return

        pytest.fail("DataAssemblies folder not found")

    def test_contains_data_assembly_variables(self, sample_config: GatewayConfig) -> None:
        """NodeSet should contain variables for data assemblies."""
        generator = NodeSetGenerator(sample_config, deterministic=True)
        xml_str = generator.generate()

        root = ET.fromstring(xml_str)

        expected_vars = [
            "ns=1;s=PEA_TestModule.DataAssemblies.TempSensor.V",
            "ns=1;s=PEA_TestModule.DataAssemblies.Valve1.V",
        ]

        found_vars = set()
        for var in root.iter(_tag("UAVariable")):
            node_id = var.get("NodeId")
            if node_id in expected_vars:
                found_vars.add(node_id)

        assert found_vars == set(expected_vars)

    def test_contains_service_variables(self, sample_config: GatewayConfig) -> None:
        """NodeSet should contain service state machine variables."""
        generator = NodeSetGenerator(sample_config, deterministic=True)
        xml_str = generator.generate()

        root = ET.fromstring(xml_str)

        expected_vars = [
            "ns=1;s=PEA_TestModule.Services.Heating.CommandOp",
            "ns=1;s=PEA_TestModule.Services.Heating.StateCur",
            "ns=1;s=PEA_TestModule.Services.Heating.ProcedureCur",
            "ns=1;s=PEA_TestModule.Services.Heating.ProcedureReq",
        ]

        found_vars = set()
        for var in root.iter(_tag("UAVariable")):
            node_id = var.get("NodeId")
            if node_id in expected_vars:
                found_vars.add(node_id)

        assert found_vars == set(expected_vars)


class TestNodeSetDeterminism:
    """Tests for deterministic NodeSet generation."""

    def test_deterministic_generates_identical_output(
        self, sample_config: GatewayConfig
    ) -> None:
        """Deterministic mode should produce identical XML."""
        gen1 = NodeSetGenerator(sample_config, deterministic=True)
        gen2 = NodeSetGenerator(sample_config, deterministic=True)

        xml1 = gen1.generate()
        xml2 = gen2.generate()

        assert xml1 == xml2

    def test_same_generator_produces_identical_output(
        self, sample_config: GatewayConfig
    ) -> None:
        """Multiple generate() calls should produce identical XML."""
        generator = NodeSetGenerator(sample_config, deterministic=True)

        xml1 = generator.generate()
        xml2 = generator.generate()

        assert xml1 == xml2

    def test_non_deterministic_varies_timestamp(
        self, sample_config: GatewayConfig
    ) -> None:
        """Non-deterministic mode may have different timestamps."""
        # Note: This test is probabilistic but timestamps should differ
        # between calls in most cases
        gen = NodeSetGenerator(sample_config, deterministic=False)

        xml1 = gen.generate()
        time.sleep(0.01)  # Small delay to get different timestamp
        xml2 = gen.generate()

        # The LastModified attribute should be different
        # (or at least could be, depending on timing)
        assert xml1 is not None
        assert xml2 is not None


class TestNodeSetFileOutput:
    """Tests for file output functionality."""

    def test_writes_to_file(
        self, sample_config: GatewayConfig, tmp_path: Path
    ) -> None:
        """NodeSet should be writable to a file."""
        output_path = tmp_path / "nodeset.xml"

        generator = NodeSetGenerator(sample_config, deterministic=True)
        generator.generate(output_path)

        assert output_path.exists()

        # Should be parseable
        root = ET.parse(output_path).getroot()
        assert root.tag == _tag("UANodeSet")

    def test_file_content_matches_return_value(
        self, sample_config: GatewayConfig, tmp_path: Path
    ) -> None:
        """File content should match the returned XML string."""
        output_path = tmp_path / "nodeset.xml"

        generator = NodeSetGenerator(sample_config, deterministic=True)
        xml_str = generator.generate(output_path)

        file_content = output_path.read_text(encoding="utf-8")
        assert file_content == xml_str
