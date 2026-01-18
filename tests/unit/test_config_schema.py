"""Unit tests for configuration schema validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mtp_gateway.config.schema import (
    ComparisonOp,
    ConnectorType,
    DataAssemblyConfig,
    DataTypeConfig,
    GatewayConfig,
    GatewayInfo,
    InterlockBindingConfig,
    ModbusTCPConnectorConfig,
    MonitorLimitsConfig,
    TagConfig,
)


class TestGatewayInfo:
    """Tests for GatewayInfo model."""

    def test_valid_gateway_info(self) -> None:
        info = GatewayInfo(name="TestGateway", version="1.0.0")
        assert info.name == "TestGateway"
        assert info.version == "1.0.0"

    def test_empty_name_fails(self) -> None:
        with pytest.raises(ValidationError):
            GatewayInfo(name="", version="1.0.0")

    def test_default_version(self) -> None:
        info = GatewayInfo(name="Test")
        assert info.version == "1.0.0"


class TestModbusTCPConnectorConfig:
    """Tests for Modbus TCP connector configuration."""

    def test_valid_modbus_config(self) -> None:
        config = ModbusTCPConnectorConfig(
            name="plc1",
            host="192.168.1.100",
            port=502,
        )
        assert config.type == ConnectorType.MODBUS_TCP
        assert config.host == "192.168.1.100"
        assert config.port == 502
        assert config.unit_id == 1  # default

    def test_custom_unit_id(self) -> None:
        config = ModbusTCPConnectorConfig(
            name="plc1",
            host="192.168.1.100",
            unit_id=5,
        )
        assert config.unit_id == 5

    def test_invalid_port(self) -> None:
        with pytest.raises(ValidationError):
            ModbusTCPConnectorConfig(
                name="plc1",
                host="192.168.1.100",
                port=70000,  # Invalid port
            )

    def test_invalid_unit_id(self) -> None:
        with pytest.raises(ValidationError):
            ModbusTCPConnectorConfig(
                name="plc1",
                host="192.168.1.100",
                unit_id=300,  # Max is 255
            )


class TestTagConfig:
    """Tests for tag configuration."""

    def test_valid_tag(self) -> None:
        tag = TagConfig(
            name="temp_sensor",
            connector="plc1",
            address="40001",
            datatype=DataTypeConfig.FLOAT32,
        )
        assert tag.name == "temp_sensor"
        assert tag.writable is False  # default

    def test_tag_with_scale(self) -> None:
        tag = TagConfig(
            name="pressure",
            connector="plc1",
            address="40002",
            datatype=DataTypeConfig.INT16,
            scale={"gain": 0.1, "offset": 0},
        )
        assert tag.scale is not None
        assert tag.scale.gain == 0.1
        assert tag.scale.offset == 0.0

    def test_empty_address_fails(self) -> None:
        with pytest.raises(ValidationError):
            TagConfig(
                name="bad_tag",
                connector="plc1",
                address="  ",  # Empty after strip
                datatype=DataTypeConfig.FLOAT32,
            )


class TestGatewayConfig:
    """Tests for full gateway configuration."""

    def test_minimal_config(self) -> None:
        config = GatewayConfig(
            gateway=GatewayInfo(name="Test"),
        )
        assert config.gateway.name == "Test"
        assert len(config.connectors) == 0
        assert len(config.tags) == 0

    def test_config_with_connectors_and_tags(self) -> None:
        config = GatewayConfig(
            gateway=GatewayInfo(name="Test"),
            connectors=[
                ModbusTCPConnectorConfig(name="plc1", host="192.168.1.100"),
            ],
            tags=[
                TagConfig(
                    name="temp",
                    connector="plc1",
                    address="40001",
                    datatype=DataTypeConfig.FLOAT32,
                ),
            ],
        )
        assert len(config.connectors) == 1
        assert len(config.tags) == 1

    def test_tag_references_unknown_connector(self) -> None:
        with pytest.raises(ValidationError, match="unknown connector"):
            GatewayConfig(
                gateway=GatewayInfo(name="Test"),
                connectors=[
                    ModbusTCPConnectorConfig(name="plc1", host="192.168.1.100"),
                ],
                tags=[
                    TagConfig(
                        name="temp",
                        connector="unknown_plc",  # Doesn't exist
                        address="40001",
                        datatype=DataTypeConfig.FLOAT32,
                    ),
                ],
            )


# =============================================================================
# MonitorLimitsConfig Tests (Phase 9)
# =============================================================================


class TestMonitorLimitsConfig:
    """Tests for MonitorLimitsConfig for analog monitor alarm limits."""

    def test_creates_with_all_none_defaults(self) -> None:
        """Should create with all limits as None by default."""
        config = MonitorLimitsConfig()

        assert config.h_limit is None
        assert config.hh_limit is None
        assert config.l_limit is None
        assert config.ll_limit is None

    def test_creates_with_custom_limits(self) -> None:
        """Should accept custom alarm limits."""
        config = MonitorLimitsConfig(
            h_limit=80.0,
            hh_limit=90.0,
            l_limit=20.0,
            ll_limit=10.0,
        )

        assert config.h_limit == 80.0
        assert config.hh_limit == 90.0
        assert config.l_limit == 20.0
        assert config.ll_limit == 10.0

    def test_partial_limits(self) -> None:
        """Should allow specifying only some limits."""
        config = MonitorLimitsConfig(h_limit=85.0)

        assert config.h_limit == 85.0
        assert config.hh_limit is None
        assert config.l_limit is None
        assert config.ll_limit is None


# =============================================================================
# InterlockBindingConfig Tests (Phase 9)
# =============================================================================


class TestInterlockBindingConfig:
    """Tests for InterlockBindingConfig for interlock source binding."""

    def test_creates_with_source_tag(self) -> None:
        """Should create with required source_tag."""
        config = InterlockBindingConfig(source_tag="Safety.Trip")

        assert config.source_tag == "Safety.Trip"
        assert config.condition == ComparisonOp.EQ  # default
        assert config.ref_value is True  # default

    def test_custom_condition(self) -> None:
        """Should accept custom comparison condition."""
        config = InterlockBindingConfig(
            source_tag="Temp.Value",
            condition=ComparisonOp.GT,
            ref_value=100.0,
        )

        assert config.source_tag == "Temp.Value"
        assert config.condition == ComparisonOp.GT
        assert config.ref_value == 100.0

    def test_all_comparison_operators(self) -> None:
        """Should support all ComparisonOp values."""
        for op in ComparisonOp:
            config = InterlockBindingConfig(
                source_tag="Tag",
                condition=op,
                ref_value=0,
            )
            assert config.condition == op

    def test_boolean_ref_value(self) -> None:
        """Should accept boolean ref_value."""
        config = InterlockBindingConfig(
            source_tag="Alarm.Active",
            ref_value=True,
        )
        assert config.ref_value is True

    def test_numeric_ref_value(self) -> None:
        """Should accept numeric ref_value."""
        config = InterlockBindingConfig(
            source_tag="Level",
            condition=ComparisonOp.LT,
            ref_value=10.5,
        )
        assert config.ref_value == 10.5

    def test_string_ref_value(self) -> None:
        """Should accept string ref_value."""
        config = InterlockBindingConfig(
            source_tag="Status",
            condition=ComparisonOp.NE,
            ref_value="OK",
        )
        assert config.ref_value == "OK"


# =============================================================================
# DataAssemblyConfig with Monitor/Interlock Extensions (Phase 9)
# =============================================================================


class TestDataAssemblyConfigExtensions:
    """Tests for DataAssemblyConfig monitor_limits and interlock_binding."""

    def test_data_assembly_with_monitor_limits(self) -> None:
        """Should accept monitor_limits for AnaMon type."""
        config = DataAssemblyConfig(
            name="TempMon",
            type="AnaMon",
            bindings={"V": "Temp.Value"},
            monitor_limits=MonitorLimitsConfig(
                h_limit=80.0,
                hh_limit=90.0,
            ),
        )

        assert config.monitor_limits is not None
        assert config.monitor_limits.h_limit == 80.0
        assert config.monitor_limits.hh_limit == 90.0

    def test_data_assembly_with_interlock_binding(self) -> None:
        """Should accept interlock_binding for active element types."""
        config = DataAssemblyConfig(
            name="Valve1",
            type="BinVlv",
            bindings={"V": "Valve.Cmd"},
            interlock_binding=InterlockBindingConfig(
                source_tag="Safety.Trip",
            ),
        )

        assert config.interlock_binding is not None
        assert config.interlock_binding.source_tag == "Safety.Trip"

    def test_data_assembly_without_extensions(self) -> None:
        """Should work without optional extensions."""
        config = DataAssemblyConfig(
            name="SimpleView",
            type="AnaView",
            bindings={"V": "Tag1"},
        )

        assert config.monitor_limits is None
        assert config.interlock_binding is None
