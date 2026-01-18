"""Tests for manifest generation determinism and round-trip parsing.

These tests verify:
1. Same config produces byte-identical manifests (determinism)
2. Generated manifests can be parsed back to extract structure
3. Node IDs are consistent and reproducible
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest

from mtp_gateway.adapters.northbound.manifest.generator import MTPManifestGenerator
from mtp_gateway.adapters.northbound.manifest.parser import ManifestParser
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

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def sample_config() -> GatewayConfig:
    """Create a sample gateway configuration for testing."""
    return GatewayConfig(
        gateway=GatewayInfo(
            name="TestReactor",
            version="1.0.0",
            description="Test reactor for determinism testing",
        ),
        opcua=OPCUAConfig(
            endpoint="opc.tcp://localhost:4840",
            namespace_uri="urn:test:reactor",
        ),
        connectors=[
            ModbusTCPConnectorConfig(name="plc1", host="192.168.1.100"),
        ],
        tags=[
            TagConfig(
                name="temp_value",
                connector="plc1",
                address="40001",
                datatype=DataTypeConfig.FLOAT32,
            ),
            TagConfig(
                name="temp_unit",
                connector="plc1",
                address="40003",
                datatype=DataTypeConfig.UINT16,
            ),
            TagConfig(
                name="valve_state",
                connector="plc1",
                address="40005",
                datatype=DataTypeConfig.BOOL,
            ),
            TagConfig(
                name="valve_safe",
                connector="plc1",
                address="40006",
                datatype=DataTypeConfig.BOOL,
            ),
        ],
        mtp=MTPConfig(
            data_assemblies=[
                DataAssemblyConfig(
                    name="TempSensor",
                    type="AnaView",
                    bindings={"V": "temp_value", "VUnit": "temp_unit"},
                    description="Temperature sensor",
                ),
                DataAssemblyConfig(
                    name="Valve1",
                    type="BinVlv",
                    bindings={"V": "valve_state", "SafePos": "valve_safe"},
                ),
            ],
            services=[
                ServiceConfig(
                    name="Heating",
                    mode=ProxyMode.THICK,
                    procedures=[
                        ProcedureConfig(id=0, name="HeatUp", is_default=True),
                        ProcedureConfig(id=1, name="Maintain"),
                    ],
                ),
                ServiceConfig(
                    name="Mixing",
                    mode=ProxyMode.THIN,
                    procedures=[
                        ProcedureConfig(id=0, name="Mix", is_default=True),
                    ],
                ),
            ],
        ),
    )


class TestManifestDeterminism:
    """Tests for deterministic manifest generation."""

    def test_manifest_generation_is_deterministic(self, sample_config: GatewayConfig) -> None:
        """Same configuration should produce byte-identical manifests."""
        generator = MTPManifestGenerator(sample_config, deterministic=True)

        # Generate manifest twice
        xml1 = generator.generate()
        xml2 = generator.generate()

        # Should be byte-identical
        assert xml1 == xml2, "Manifest generation should be deterministic"

        # Hash should be identical
        hash1 = hashlib.sha256(xml1.encode()).hexdigest()
        hash2 = hashlib.sha256(xml2.encode()).hexdigest()
        assert hash1 == hash2

    def test_deterministic_uuid_from_config_hash(self, sample_config: GatewayConfig) -> None:
        """UUIDs should be derived from config content, not random."""
        gen1 = MTPManifestGenerator(sample_config, deterministic=True)
        gen2 = MTPManifestGenerator(sample_config, deterministic=True)

        xml1 = gen1.generate()
        xml2 = gen2.generate()

        # Different generator instances with same config should produce same output
        assert xml1 == xml2

    def test_different_configs_produce_different_manifests(
        self, sample_config: GatewayConfig
    ) -> None:
        """Different configurations should produce different manifests."""
        gen1 = MTPManifestGenerator(sample_config, deterministic=True)
        xml1 = gen1.generate()

        # Modify config
        modified_config = sample_config.model_copy(deep=True)
        modified_config.gateway.name = "ModifiedReactor"

        gen2 = MTPManifestGenerator(modified_config, deterministic=True)
        xml2 = gen2.generate()

        assert xml1 != xml2, "Different configs should produce different manifests"

    def test_non_deterministic_mode_uses_random_uuids(self, sample_config: GatewayConfig) -> None:
        """Default (non-deterministic) mode should use random UUIDs."""
        gen1 = MTPManifestGenerator(sample_config, deterministic=False)
        gen2 = MTPManifestGenerator(sample_config, deterministic=False)

        xml1 = gen1.generate()
        xml2 = gen2.generate()

        # UUIDs are random, so manifests should differ (with high probability)
        # We check that at least one ID differs
        assert xml1 != xml2, "Non-deterministic mode should produce different UUIDs"


class TestManifestParser:
    """Tests for manifest parsing."""

    def test_parser_extracts_node_ids(self, sample_config: GatewayConfig) -> None:
        """Parser should extract all OPC UA node IDs from manifest."""
        generator = MTPManifestGenerator(sample_config, deterministic=True)
        xml = generator.generate()

        parser = ManifestParser(xml)
        node_ids = parser.extract_node_ids()

        # Should find node IDs for data assemblies and services
        assert len(node_ids) > 0, "Should extract node IDs"

        # Check for expected patterns
        assert any("TempSensor" in nid for nid in node_ids), "Should find TempSensor node IDs"
        assert any("Valve1" in nid for nid in node_ids), "Should find Valve1 node IDs"
        assert any("Heating" in nid for nid in node_ids), "Should find Heating service node IDs"
        assert any("Mixing" in nid for nid in node_ids), "Should find Mixing service node IDs"

    def test_parser_extracts_data_assemblies(self, sample_config: GatewayConfig) -> None:
        """Parser should extract data assembly information."""
        generator = MTPManifestGenerator(sample_config, deterministic=True)
        xml = generator.generate()

        parser = ManifestParser(xml)
        data_assemblies = parser.extract_data_assemblies()

        assert len(data_assemblies) == 2
        names = {da["name"] for da in data_assemblies}
        assert "TempSensor" in names
        assert "Valve1" in names

    def test_parser_extracts_services(self, sample_config: GatewayConfig) -> None:
        """Parser should extract service information."""
        generator = MTPManifestGenerator(sample_config, deterministic=True)
        xml = generator.generate()

        parser = ManifestParser(xml)
        services = parser.extract_services()

        assert len(services) == 2
        names = {svc["name"] for svc in services}
        assert "Heating" in names
        assert "Mixing" in names

    def test_parser_extracts_pea_info(self, sample_config: GatewayConfig) -> None:
        """Parser should extract PEA (Process Equipment Assembly) info."""
        generator = MTPManifestGenerator(sample_config, deterministic=True)
        xml = generator.generate()

        parser = ManifestParser(xml)
        pea_info = parser.extract_pea_info()

        assert pea_info["name"] == "TestReactor"
        assert pea_info["version"] == "1.0.0"


class TestManifestRoundTrip:
    """Tests for manifest generation and parsing round-trip."""

    def test_manifest_round_trip_preserves_structure(self, sample_config: GatewayConfig) -> None:
        """Generate → Parse should preserve structure."""
        generator = MTPManifestGenerator(sample_config, deterministic=True)
        xml = generator.generate()

        parser = ManifestParser(xml)

        # Check data assemblies match config
        parsed_das = parser.extract_data_assemblies()
        config_da_names = {da.name for da in sample_config.mtp.data_assemblies}
        parsed_da_names = {da["name"] for da in parsed_das}
        assert config_da_names == parsed_da_names

        # Check services match config
        parsed_services = parser.extract_services()
        config_svc_names = {svc.name for svc in sample_config.mtp.services}
        parsed_svc_names = {svc["name"] for svc in parsed_services}
        assert config_svc_names == parsed_svc_names

    def test_node_ids_match_generator_output(self, sample_config: GatewayConfig) -> None:
        """Parsed node IDs should match generator's get_all_node_ids()."""
        generator = MTPManifestGenerator(sample_config, deterministic=True)
        xml = generator.generate()

        expected_node_ids = set(generator.get_all_node_ids())

        parser = ManifestParser(xml)
        parsed_node_ids = parser.extract_node_ids()

        assert expected_node_ids == parsed_node_ids, "Parsed node IDs should match generator output"

    def test_parse_from_file(self, sample_config: GatewayConfig, tmp_path: Path) -> None:
        """Parser should be able to read manifest from file."""
        manifest_path = tmp_path / "manifest.aml"

        generator = MTPManifestGenerator(sample_config, deterministic=True)
        generator.generate(manifest_path)

        parser = ManifestParser.from_file(manifest_path)
        node_ids = parser.extract_node_ids()

        assert len(node_ids) > 0
