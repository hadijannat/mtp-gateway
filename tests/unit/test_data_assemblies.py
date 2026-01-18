"""Unit tests for Data Assemblies (Phase 9).

Tests for:
- AnaMon: Analog monitor with limits and alarm states
- BinMon: Binary monitor with state tracking and error detection
- AnaDrv: Verify interlock/permit attributes exist (consistency fix)

These tests are written FIRST per TDD - they will fail until implementation.
"""

from __future__ import annotations

import pytest

# These imports will fail initially - classes don't exist yet
from mtp_gateway.domain.model.data_assemblies import (
    AnaMon,
    BinMon,
    AnaDrv,
    BaseDataAssembly,
    DataAssemblyType,
    InterlockedState,
    PermitState,
    create_data_assembly,
    DATA_ASSEMBLY_CLASSES,
)


# =============================================================================
# AnaMon Tests
# =============================================================================


class TestAnaMon:
    """Tests for Analog Monitor data assembly."""

    def test_creates_with_defaults(self) -> None:
        """Should create AnaMon with default values."""
        mon = AnaMon(name="TempMon", tag_name="Temp.Value")

        assert mon.name == "TempMon"
        assert mon.tag_name == "Temp.Value"
        assert mon.v == 0.0
        assert mon.v_scl_min == 0.0
        assert mon.v_scl_max == 100.0
        assert mon.v_unit == 0

    def test_da_type_is_ana_mon(self) -> None:
        """Should return ANA_MON data assembly type."""
        mon = AnaMon(name="TempMon", tag_name="Temp.Value")
        assert mon.da_type == DataAssemblyType.ANA_MON

    def test_default_alarm_limits(self) -> None:
        """Should have default alarm limits."""
        mon = AnaMon(name="TempMon", tag_name="Temp.Value")

        assert mon.h_limit == 90.0
        assert mon.hh_limit == 95.0
        assert mon.l_limit == 10.0
        assert mon.ll_limit == 5.0

    def test_default_alarm_states_are_false(self) -> None:
        """All alarm states should default to False."""
        mon = AnaMon(name="TempMon", tag_name="Temp.Value")

        assert mon.alarm_h is False
        assert mon.alarm_hh is False
        assert mon.alarm_l is False
        assert mon.alarm_ll is False

    def test_update_alarms_high_limit(self) -> None:
        """Should set alarm_h when value exceeds high limit."""
        mon = AnaMon(
            name="TempMon",
            tag_name="Temp.Value",
            v=92.0,  # Above h_limit (90) but below hh_limit (95)
            h_limit=90.0,
            hh_limit=95.0,
        )

        mon.update_alarms()

        assert mon.alarm_h is True
        assert mon.alarm_hh is False

    def test_update_alarms_high_high_limit(self) -> None:
        """Should set alarm_hh when value exceeds high-high limit."""
        mon = AnaMon(
            name="TempMon",
            tag_name="Temp.Value",
            v=97.0,  # Above hh_limit (95)
            h_limit=90.0,
            hh_limit=95.0,
        )

        mon.update_alarms()

        assert mon.alarm_h is True  # Also set because v > h_limit
        assert mon.alarm_hh is True

    def test_update_alarms_low_limit(self) -> None:
        """Should set alarm_l when value drops below low limit."""
        mon = AnaMon(
            name="TempMon",
            tag_name="Temp.Value",
            v=8.0,  # Below l_limit (10) but above ll_limit (5)
            l_limit=10.0,
            ll_limit=5.0,
        )

        mon.update_alarms()

        assert mon.alarm_l is True
        assert mon.alarm_ll is False

    def test_update_alarms_low_low_limit(self) -> None:
        """Should set alarm_ll when value drops below low-low limit."""
        mon = AnaMon(
            name="TempMon",
            tag_name="Temp.Value",
            v=3.0,  # Below ll_limit (5)
            l_limit=10.0,
            ll_limit=5.0,
        )

        mon.update_alarms()

        assert mon.alarm_l is True  # Also set because v < l_limit
        assert mon.alarm_ll is True

    def test_update_alarms_no_alarm_in_range(self) -> None:
        """No alarms when value is within normal range."""
        mon = AnaMon(
            name="TempMon",
            tag_name="Temp.Value",
            v=50.0,  # Normal range
            h_limit=90.0,
            hh_limit=95.0,
            l_limit=10.0,
            ll_limit=5.0,
        )

        mon.update_alarms()

        assert mon.alarm_h is False
        assert mon.alarm_hh is False
        assert mon.alarm_l is False
        assert mon.alarm_ll is False

    def test_update_alarms_clears_previous_alarms(self) -> None:
        """update_alarms() should clear alarms when value returns to normal."""
        mon = AnaMon(
            name="TempMon",
            tag_name="Temp.Value",
            v=97.0,  # High alarm
            h_limit=90.0,
            hh_limit=95.0,
        )
        mon.update_alarms()
        assert mon.alarm_hh is True

        # Value returns to normal
        mon.v = 50.0
        mon.update_alarms()

        assert mon.alarm_h is False
        assert mon.alarm_hh is False

    def test_get_bindings_returns_v_tag(self) -> None:
        """get_bindings() should return primary value binding."""
        mon = AnaMon(name="TempMon", tag_name="Temp.Value")

        bindings = mon.get_bindings()

        assert bindings["V"] == "Temp.Value"

    def test_custom_limits(self) -> None:
        """Should accept custom alarm limits."""
        mon = AnaMon(
            name="TempMon",
            tag_name="Temp.Value",
            h_limit=80.0,
            hh_limit=90.0,
            l_limit=20.0,
            ll_limit=10.0,
        )

        assert mon.h_limit == 80.0
        assert mon.hh_limit == 90.0
        assert mon.l_limit == 20.0
        assert mon.ll_limit == 10.0

    def test_scaling_attributes(self) -> None:
        """Should store scaling attributes."""
        mon = AnaMon(
            name="TempMon",
            tag_name="Temp.Value",
            v_scl_min=-40.0,
            v_scl_max=120.0,
            v_unit=1001,  # Celsius unit code
        )

        assert mon.v_scl_min == -40.0
        assert mon.v_scl_max == 120.0
        assert mon.v_unit == 1001

    def test_is_base_data_assembly(self) -> None:
        """AnaMon should be a BaseDataAssembly."""
        mon = AnaMon(name="TempMon", tag_name="Temp.Value")
        assert isinstance(mon, BaseDataAssembly)


# =============================================================================
# BinMon Tests
# =============================================================================


class TestBinMon:
    """Tests for Binary Monitor data assembly."""

    def test_creates_with_defaults(self) -> None:
        """Should create BinMon with default values."""
        mon = BinMon(name="DoorMon", tag_name="Door.Status")

        assert mon.name == "DoorMon"
        assert mon.tag_name == "Door.Status"
        assert mon.v is False
        assert mon.v_state_0 == "Off"
        assert mon.v_state_1 == "On"

    def test_da_type_is_bin_mon(self) -> None:
        """Should return BIN_MON data assembly type."""
        mon = BinMon(name="DoorMon", tag_name="Door.Status")
        assert mon.da_type == DataAssemblyType.BIN_MON

    def test_default_state_error_is_false(self) -> None:
        """mon_state_err should default to False."""
        mon = BinMon(name="DoorMon", tag_name="Door.Status")
        assert mon.mon_state_err is False

    def test_expected_state_default_is_none(self) -> None:
        """expected_state should default to None (no expectation)."""
        mon = BinMon(name="DoorMon", tag_name="Door.Status")
        assert mon.expected_state is None

    def test_state_error_detection_when_mismatch(self) -> None:
        """Should detect state error when value doesn't match expected."""
        mon = BinMon(
            name="DoorMon",
            tag_name="Door.Status",
            v=False,
            expected_state=True,  # Expected on, but is off
        )

        mon.update_state_error()

        assert mon.mon_state_err is True

    def test_no_state_error_when_matches(self) -> None:
        """No state error when value matches expected."""
        mon = BinMon(
            name="DoorMon",
            tag_name="Door.Status",
            v=True,
            expected_state=True,  # Expected on, and is on
        )

        mon.update_state_error()

        assert mon.mon_state_err is False

    def test_no_state_error_when_no_expectation(self) -> None:
        """No state error when expected_state is None."""
        mon = BinMon(
            name="DoorMon",
            tag_name="Door.Status",
            v=True,
            expected_state=None,
        )

        mon.update_state_error()

        assert mon.mon_state_err is False

    def test_state_error_clears_when_value_changes(self) -> None:
        """State error should clear when value matches expectation."""
        mon = BinMon(
            name="DoorMon",
            tag_name="Door.Status",
            v=False,
            expected_state=True,
        )
        mon.update_state_error()
        assert mon.mon_state_err is True

        # Value changes to match
        mon.v = True
        mon.update_state_error()

        assert mon.mon_state_err is False

    def test_get_bindings_returns_v_tag(self) -> None:
        """get_bindings() should return primary value binding."""
        mon = BinMon(name="DoorMon", tag_name="Door.Status")

        bindings = mon.get_bindings()

        assert bindings["V"] == "Door.Status"

    def test_custom_state_labels(self) -> None:
        """Should accept custom state labels."""
        mon = BinMon(
            name="DoorMon",
            tag_name="Door.Status",
            v_state_0="Closed",
            v_state_1="Open",
        )

        assert mon.v_state_0 == "Closed"
        assert mon.v_state_1 == "Open"

    def test_is_base_data_assembly(self) -> None:
        """BinMon should be a BaseDataAssembly."""
        mon = BinMon(name="DoorMon", tag_name="Door.Status")
        assert isinstance(mon, BaseDataAssembly)


# =============================================================================
# AnaDrv Consistency Tests (interlock/permit attributes)
# =============================================================================


class TestAnaDrvConsistency:
    """Tests to ensure AnaDrv has interlock/permit like other active elements."""

    def test_has_interlock_attribute(self) -> None:
        """AnaDrv should have interlock attribute like BinDrv."""
        drv = AnaDrv(name="VFD", tag_name="Motor.Speed")
        assert hasattr(drv, "interlock")
        assert drv.interlock == InterlockedState.NOT_INTERLOCKED

    def test_has_permit_attribute(self) -> None:
        """AnaDrv should have permit attribute like BinDrv."""
        drv = AnaDrv(name="VFD", tag_name="Motor.Speed")
        assert hasattr(drv, "permit")
        assert drv.permit == PermitState.PERMITTED

    def test_can_set_interlocked(self) -> None:
        """Should be able to set AnaDrv to interlocked state."""
        drv = AnaDrv(
            name="VFD",
            tag_name="Motor.Speed",
            interlock=InterlockedState.INTERLOCKED,
        )
        assert drv.interlock == InterlockedState.INTERLOCKED

    def test_can_set_not_permitted(self) -> None:
        """Should be able to set AnaDrv to not permitted."""
        drv = AnaDrv(
            name="VFD",
            tag_name="Motor.Speed",
            permit=PermitState.NOT_PERMITTED,
        )
        assert drv.permit == PermitState.NOT_PERMITTED


# =============================================================================
# Factory Function Tests
# =============================================================================


class TestDataAssemblyFactory:
    """Tests for create_data_assembly() factory function."""

    def test_creates_ana_mon(self) -> None:
        """Factory should create AnaMon from type string."""
        mon = create_data_assembly(
            da_type="AnaMon",
            name="TempMon",
            tag_name="Temp.Value",
        )

        assert isinstance(mon, AnaMon)
        assert mon.name == "TempMon"

    def test_creates_bin_mon(self) -> None:
        """Factory should create BinMon from type string."""
        mon = create_data_assembly(
            da_type="BinMon",
            name="DoorMon",
            tag_name="Door.Status",
        )

        assert isinstance(mon, BinMon)
        assert mon.name == "DoorMon"

    def test_ana_mon_in_class_registry(self) -> None:
        """AnaMon should be in DATA_ASSEMBLY_CLASSES registry."""
        assert "AnaMon" in DATA_ASSEMBLY_CLASSES

    def test_bin_mon_in_class_registry(self) -> None:
        """BinMon should be in DATA_ASSEMBLY_CLASSES registry."""
        assert "BinMon" in DATA_ASSEMBLY_CLASSES

    def test_creates_ana_mon_with_kwargs(self) -> None:
        """Factory should pass kwargs to AnaMon."""
        mon = create_data_assembly(
            da_type="AnaMon",
            name="TempMon",
            tag_name="Temp.Value",
            h_limit=85.0,
            hh_limit=90.0,
        )

        assert isinstance(mon, AnaMon)
        assert mon.h_limit == 85.0
        assert mon.hh_limit == 90.0

    def test_creates_bin_mon_with_kwargs(self) -> None:
        """Factory should pass kwargs to BinMon."""
        mon = create_data_assembly(
            da_type="BinMon",
            name="DoorMon",
            tag_name="Door.Status",
            v_state_0="Closed",
            v_state_1="Open",
        )

        assert isinstance(mon, BinMon)
        assert mon.v_state_0 == "Closed"
        assert mon.v_state_1 == "Open"


# =============================================================================
# Node ID Generation Tests
# =============================================================================


class TestNodeIdGeneration:
    """Tests for OPC UA NodeID path generation."""

    def test_ana_mon_node_id_base(self) -> None:
        """AnaMon should generate correct NodeID base path."""
        mon = AnaMon(name="TempMon", tag_name="Temp.Value")

        node_id = mon.get_node_id_base("ReactorA")

        assert node_id == "PEA_ReactorA.DataAssemblies.TempMon"

    def test_bin_mon_node_id_base(self) -> None:
        """BinMon should generate correct NodeID base path."""
        mon = BinMon(name="DoorMon", tag_name="Door.Status")

        node_id = mon.get_node_id_base("ReactorA")

        assert node_id == "PEA_ReactorA.DataAssemblies.DoorMon"
