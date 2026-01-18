"""Unit tests for OPC UA NodeSet generation."""

from __future__ import annotations

from mtp_gateway.adapters.northbound.nodeset.generator import NodeSetGenerator
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
        gateway=GatewayInfo(name="NodeSetPEA", version="0.1.0"),
        opcua=OPCUAConfig(
            endpoint="opc.tcp://localhost:4840",
            namespace_uri="urn:test:nodeset",
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
            services=[ServiceConfig(name="Mixing")],
        ),
    )


def test_nodeset_xml_contains_namespace_and_pea() -> None:
    config = _sample_config()
    generator = NodeSetGenerator(config, deterministic=True)
    xml = generator.generate()
    assert "UANodeSet" in xml
    assert "NamespaceUris" in xml
    assert "PEA_NodeSetPEA" in xml


def test_nodeset_includes_services_and_data_assemblies() -> None:
    config = _sample_config()
    generator = NodeSetGenerator(config, deterministic=True)
    xml = generator.generate()
    assert "DataAssemblies" in xml
    assert "Services" in xml
    assert "TempSensor" in xml
    assert "Mixing" in xml
