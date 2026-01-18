"""Unit tests for manifest parser."""

from __future__ import annotations

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
    ServiceConfig,
    TagConfig,
)


def _sample_config() -> GatewayConfig:
    return GatewayConfig(
        gateway=GatewayInfo(name="ParserPEA", version="1.0.0"),
        opcua=OPCUAConfig(
            endpoint="opc.tcp://localhost:4840",
            namespace_uri="urn:test:parser",
        ),
        connectors=[ModbusTCPConnectorConfig(name="plc1", host="127.0.0.1")],
        tags=[
            TagConfig(
                name="temp",
                connector="plc1",
                address="40001",
                datatype=DataTypeConfig.FLOAT32,
            )
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


def test_parser_extracts_node_ids() -> None:
    config = _sample_config()
    generator = MTPManifestGenerator(config, deterministic=True)
    xml = generator.generate()
    parser = ManifestParser(xml)
    node_ids = parser.extract_node_ids()
    assert any("TempSensor" in node_id for node_id in node_ids)
    assert any("Dosing" in node_id for node_id in node_ids)
