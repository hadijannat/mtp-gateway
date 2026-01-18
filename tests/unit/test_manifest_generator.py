"""Unit tests for MTP manifest generation."""

from __future__ import annotations

import zipfile

from mtp_gateway.adapters.northbound.manifest.generator import MTPManifestGenerator
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


def _sample_config() -> GatewayConfig:
    return GatewayConfig(
        gateway=GatewayInfo(name="UnitTestPEA", version="1.2.3"),
        opcua=OPCUAConfig(
            endpoint="opc.tcp://localhost:4840",
            namespace_uri="urn:test:pea",
        ),
        connectors=[ModbusTCPConnectorConfig(name="plc1", host="127.0.0.1")],
        tags=[
            TagConfig(
                name="temp",
                connector="plc1",
                address="40001",
                datatype=DataTypeConfig.FLOAT32,
            ),
            TagConfig(
                name="cmd",
                connector="plc1",
                address="00001",
                datatype=DataTypeConfig.BOOL,
                writable=True,
            ),
        ],
        mtp=MTPConfig(
            data_assemblies=[
                DataAssemblyConfig(
                    name="TempSensor",
                    type="AnaView",
                    bindings={"V": "temp"},
                )
            ],
            services=[ServiceConfig(name="Dosing")],
        ),
    )


def test_generate_manifest_contains_required_sections() -> None:
    config = _sample_config()
    generator = MTPManifestGenerator(config, deterministic=True)
    xml = generator.generate()
    assert "CAEXFile" in xml
    assert "InstanceHierarchy" in xml
    assert "OPCUAServer" in xml
    assert "TempSensor" in xml
    assert "Dosing" in xml


def test_get_all_node_ids_includes_services_and_data_assemblies() -> None:
    config = _sample_config()
    generator = MTPManifestGenerator(config)
    node_ids = generator.get_all_node_ids()
    assert any("TempSensor" in node_id for node_id in node_ids)
    assert any("Dosing" in node_id for node_id in node_ids)


def test_generate_package_writes_mtp_archive(tmp_path) -> None:
    config = _sample_config()
    generator = MTPManifestGenerator(config, deterministic=True)
    output = tmp_path / "module.mtp"
    generator.generate_package(output)

    assert output.exists()
    with zipfile.ZipFile(output, "r") as zf:
        names = set(zf.namelist())
        assert "manifest.aml" in names
        assert "manifest.info" in names
