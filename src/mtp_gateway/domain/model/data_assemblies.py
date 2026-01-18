"""Data Assembly models per VDI/VDE/NAMUR 2658-4.

Data Assemblies are the building blocks of MTP interfaces, providing
standardized data structures for process values, parameters, and
active elements (valves, drives, controllers).

Categories:
- View (read-only): AnaView, BinView, DIntView, StringView
- ServParam (writable): AnaServParam, BinServParam, DIntServParam, StringServParam
- Active Elements: AnaVlv, BinVlv, AnaDrv, BinDrv, PIDCtrl
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any


class DataAssemblyType(Enum):
    """MTP Data Assembly types per VDI 2658-4."""

    # Read-only views
    ANA_VIEW = "AnaView"
    BIN_VIEW = "BinView"
    DINT_VIEW = "DIntView"
    STRING_VIEW = "StringView"

    # Writable service parameters
    ANA_SERV_PARAM = "AnaServParam"
    BIN_SERV_PARAM = "BinServParam"
    DINT_SERV_PARAM = "DIntServParam"
    STRING_SERV_PARAM = "StringServParam"

    # Active elements
    ANA_VLV = "AnaVlv"
    BIN_VLV = "BinVlv"
    ANA_DRV = "AnaDrv"
    BIN_DRV = "BinDrv"
    PID_CTRL = "PIDCtrl"
    ANA_MON = "AnaMon"
    BIN_MON = "BinMon"


class OperationMode(Enum):
    """Operating mode for active elements."""

    OFF = 0
    OPERATOR = 1  # Manual control via operator
    AUTOMATIC = 2  # POL-controlled


class SourceMode(Enum):
    """Source mode indicating who controls the value."""

    OFF = 0
    MANUAL = 1
    AUTOMATIC = 2


class InterlockedState(Enum):
    """Interlock state for safety."""

    NOT_INTERLOCKED = 0
    INTERLOCKED = 1


class PermitState(Enum):
    """Permit state for operation."""

    NOT_PERMITTED = 0
    PERMITTED = 1


@dataclass
class BaseDataAssembly(ABC):
    """Base class for all MTP Data Assemblies.

    Common attributes shared by all data assembly types.
    """

    name: str
    tag_name: str  # Reference to the underlying tag
    description: str = ""

    # Common MTP attributes
    wqc: int = 0  # Worst quality code

    @property
    @abstractmethod
    def da_type(self) -> DataAssemblyType:
        """Return the data assembly type."""
        ...

    @abstractmethod
    def get_bindings(self) -> dict[str, str]:
        """Return tag bindings for this assembly."""
        ...

    def get_node_id_base(self, pea_name: str) -> str:
        """Generate deterministic NodeID base path."""
        return f"PEA_{pea_name}.DataAssemblies.{self.name}"


# =============================================================================
# READ-ONLY VIEW ASSEMBLIES
# =============================================================================


@dataclass
class AnaView(BaseDataAssembly):
    """Analog View - read-only analog process value.

    Displays an analog value with scaling, limits, and units.
    """

    # Primary value bindings
    v_tag: str = ""  # Current value
    v_scl_min: float = 0.0  # Scale minimum
    v_scl_max: float = 100.0  # Scale maximum
    v_unit: int = 0  # Engineering unit code

    # Optional limit bindings
    v_hh_lim: float | None = None  # High-high limit
    v_h_lim: float | None = None  # High limit
    v_l_lim: float | None = None  # Low limit
    v_ll_lim: float | None = None  # Low-low limit

    # Alarm state
    v_hh_act: bool = False
    v_h_act: bool = False
    v_l_act: bool = False
    v_ll_act: bool = False

    @property
    def da_type(self) -> DataAssemblyType:
        return DataAssemblyType.ANA_VIEW

    def get_bindings(self) -> dict[str, str]:
        bindings = {"V": self.v_tag or self.tag_name}
        return bindings


@dataclass
class BinView(BaseDataAssembly):
    """Binary View - read-only binary/boolean process value."""

    v_tag: str = ""  # Current value (True/False)
    v_state_0: str = "Off"  # Text for False state
    v_state_1: str = "On"  # Text for True state

    @property
    def da_type(self) -> DataAssemblyType:
        return DataAssemblyType.BIN_VIEW

    def get_bindings(self) -> dict[str, str]:
        return {"V": self.v_tag or self.tag_name}


@dataclass
class DIntView(BaseDataAssembly):
    """Digital Integer View - read-only integer value."""

    v_tag: str = ""
    v_scl_min: int = 0
    v_scl_max: int = 65535
    v_unit: int = 0

    @property
    def da_type(self) -> DataAssemblyType:
        return DataAssemblyType.DINT_VIEW

    def get_bindings(self) -> dict[str, str]:
        return {"V": self.v_tag or self.tag_name}


@dataclass
class StringView(BaseDataAssembly):
    """String View - read-only string value."""

    v_tag: str = ""

    @property
    def da_type(self) -> DataAssemblyType:
        return DataAssemblyType.STRING_VIEW

    def get_bindings(self) -> dict[str, str]:
        return {"V": self.v_tag or self.tag_name}


# =============================================================================
# WRITABLE SERVICE PARAMETER ASSEMBLIES
# =============================================================================


@dataclass
class AnaServParam(BaseDataAssembly):
    """Analog Service Parameter - writable analog value.

    Used for setpoints and configuration parameters that can be
    modified by the POL during service execution.
    """

    # Primary value
    v_tag: str = ""  # Current external value
    v_int_tag: str = ""  # Internal value (from POL)
    v_req_tag: str = ""  # Requested value
    v_scl_min: float = 0.0
    v_scl_max: float = 100.0
    v_unit: int = 0
    v_op_min: float = 0.0  # Operator minimum
    v_op_max: float = 100.0  # Operator maximum

    # Mode control
    src_mode: SourceMode = SourceMode.AUTOMATIC
    src_int_act: bool = False  # Internal source active
    src_ext_act: bool = True  # External source active

    @property
    def da_type(self) -> DataAssemblyType:
        return DataAssemblyType.ANA_SERV_PARAM

    def get_bindings(self) -> dict[str, str]:
        bindings = {"V": self.v_tag or self.tag_name}
        if self.v_int_tag:
            bindings["VInt"] = self.v_int_tag
        if self.v_req_tag:
            bindings["VReq"] = self.v_req_tag
        return bindings


@dataclass
class BinServParam(BaseDataAssembly):
    """Binary Service Parameter - writable binary value."""

    v_tag: str = ""
    v_int_tag: str = ""
    v_req_tag: str = ""
    v_state_0: str = "Off"
    v_state_1: str = "On"

    src_mode: SourceMode = SourceMode.AUTOMATIC
    src_int_act: bool = False
    src_ext_act: bool = True

    @property
    def da_type(self) -> DataAssemblyType:
        return DataAssemblyType.BIN_SERV_PARAM

    def get_bindings(self) -> dict[str, str]:
        bindings = {"V": self.v_tag or self.tag_name}
        if self.v_int_tag:
            bindings["VInt"] = self.v_int_tag
        if self.v_req_tag:
            bindings["VReq"] = self.v_req_tag
        return bindings


@dataclass
class DIntServParam(BaseDataAssembly):
    """Digital Integer Service Parameter - writable integer value."""

    v_tag: str = ""
    v_int_tag: str = ""
    v_req_tag: str = ""
    v_scl_min: int = 0
    v_scl_max: int = 65535
    v_unit: int = 0
    v_op_min: int = 0
    v_op_max: int = 65535

    src_mode: SourceMode = SourceMode.AUTOMATIC

    @property
    def da_type(self) -> DataAssemblyType:
        return DataAssemblyType.DINT_SERV_PARAM

    def get_bindings(self) -> dict[str, str]:
        bindings = {"V": self.v_tag or self.tag_name}
        if self.v_int_tag:
            bindings["VInt"] = self.v_int_tag
        if self.v_req_tag:
            bindings["VReq"] = self.v_req_tag
        return bindings


@dataclass
class StringServParam(BaseDataAssembly):
    """String Service Parameter - writable string value."""

    v_tag: str = ""
    v_int_tag: str = ""
    max_length: int = 255

    @property
    def da_type(self) -> DataAssemblyType:
        return DataAssemblyType.STRING_SERV_PARAM

    def get_bindings(self) -> dict[str, str]:
        bindings = {"V": self.v_tag or self.tag_name}
        if self.v_int_tag:
            bindings["VInt"] = self.v_int_tag
        return bindings


# =============================================================================
# ACTIVE ELEMENT ASSEMBLIES
# =============================================================================


@dataclass
class BinVlv(BaseDataAssembly):
    """Binary Valve - on/off valve control.

    Controls a binary valve with feedback and safety interlocks.
    """

    # Command and feedback
    v_tag: str = ""  # Control output
    v_fbk_open_tag: str = ""  # Feedback open position
    v_fbk_close_tag: str = ""  # Feedback close position

    # State
    open_act: bool = False
    close_act: bool = False

    # Safety
    interlock: InterlockedState = InterlockedState.NOT_INTERLOCKED
    permit: PermitState = PermitState.PERMITTED
    protect: bool = False

    # Mode
    op_mode: OperationMode = OperationMode.AUTOMATIC
    src_mode: SourceMode = SourceMode.AUTOMATIC

    # Timing
    mon_time_open: float = 5.0  # seconds
    mon_time_close: float = 5.0

    # Alarms
    mon_pos_err: bool = False  # Position error

    @property
    def da_type(self) -> DataAssemblyType:
        return DataAssemblyType.BIN_VLV

    def get_bindings(self) -> dict[str, str]:
        bindings = {"V": self.v_tag or self.tag_name}
        if self.v_fbk_open_tag:
            bindings["VFbkOpen"] = self.v_fbk_open_tag
        if self.v_fbk_close_tag:
            bindings["VFbkClose"] = self.v_fbk_close_tag
        return bindings


@dataclass
class AnaVlv(BaseDataAssembly):
    """Analog Valve - modulating valve control.

    Controls valve position with analog setpoint and feedback.
    """

    # Setpoint and feedback
    v_tag: str = ""  # Position setpoint output
    v_fbk_tag: str = ""  # Position feedback
    v_pos_tag: str = ""  # Actual position

    # Scaling
    v_scl_min: float = 0.0
    v_scl_max: float = 100.0
    v_unit: int = 0

    # Safety
    interlock: InterlockedState = InterlockedState.NOT_INTERLOCKED
    permit: PermitState = PermitState.PERMITTED
    safe_pos: float = 0.0  # Position on safety trip

    # Mode
    op_mode: OperationMode = OperationMode.AUTOMATIC

    @property
    def da_type(self) -> DataAssemblyType:
        return DataAssemblyType.ANA_VLV

    def get_bindings(self) -> dict[str, str]:
        bindings = {"V": self.v_tag or self.tag_name}
        if self.v_fbk_tag:
            bindings["VFbk"] = self.v_fbk_tag
        if self.v_pos_tag:
            bindings["VPos"] = self.v_pos_tag
        return bindings


@dataclass
class BinDrv(BaseDataAssembly):
    """Binary Drive - on/off motor/pump control."""

    # Command and feedback
    v_tag: str = ""
    v_fbk_running_tag: str = ""
    v_fault_tag: str = ""

    # State
    running: bool = False
    fault: bool = False

    # Safety
    interlock: InterlockedState = InterlockedState.NOT_INTERLOCKED
    permit: PermitState = PermitState.PERMITTED

    # Mode
    op_mode: OperationMode = OperationMode.AUTOMATIC

    @property
    def da_type(self) -> DataAssemblyType:
        return DataAssemblyType.BIN_DRV

    def get_bindings(self) -> dict[str, str]:
        bindings = {"V": self.v_tag or self.tag_name}
        if self.v_fbk_running_tag:
            bindings["VFbkRunning"] = self.v_fbk_running_tag
        if self.v_fault_tag:
            bindings["VFault"] = self.v_fault_tag
        return bindings


@dataclass
class AnaDrv(BaseDataAssembly):
    """Analog Drive - variable speed drive control."""

    # Setpoint and feedback
    v_tag: str = ""  # Speed setpoint
    v_fbk_tag: str = ""  # Speed feedback
    v_fault_tag: str = ""

    # Scaling
    v_scl_min: float = 0.0
    v_scl_max: float = 100.0
    v_unit: int = 0

    # Limits
    v_op_min: float = 0.0
    v_op_max: float = 100.0

    # State
    running: bool = False
    fault: bool = False

    # Safety (consistency with BinDrv)
    interlock: InterlockedState = InterlockedState.NOT_INTERLOCKED
    permit: PermitState = PermitState.PERMITTED

    # Mode
    op_mode: OperationMode = OperationMode.AUTOMATIC

    @property
    def da_type(self) -> DataAssemblyType:
        return DataAssemblyType.ANA_DRV

    def get_bindings(self) -> dict[str, str]:
        bindings = {"V": self.v_tag or self.tag_name}
        if self.v_fbk_tag:
            bindings["VFbk"] = self.v_fbk_tag
        if self.v_fault_tag:
            bindings["VFault"] = self.v_fault_tag
        return bindings


@dataclass
class PIDCtrl(BaseDataAssembly):
    """PID Controller - closed-loop control."""

    # Process value
    pv_tag: str = ""  # Process variable
    pv_scl_min: float = 0.0
    pv_scl_max: float = 100.0
    pv_unit: int = 0

    # Setpoint
    sp_tag: str = ""  # Setpoint
    sp_int_tag: str = ""  # Internal setpoint (from POL)
    sp_scl_min: float = 0.0
    sp_scl_max: float = 100.0

    # Output
    mv_tag: str = ""  # Manipulated variable
    mv_scl_min: float = 0.0
    mv_scl_max: float = 100.0
    mv_unit: int = 0

    # Tuning parameters
    gain: float = 1.0
    ti: float = 10.0  # Integral time (seconds)
    td: float = 0.0  # Derivative time (seconds)

    # Mode
    op_mode: OperationMode = OperationMode.AUTOMATIC
    man_mode: bool = False  # True = manual, False = auto

    @property
    def da_type(self) -> DataAssemblyType:
        return DataAssemblyType.PID_CTRL

    def get_bindings(self) -> dict[str, str]:
        bindings: dict[str, str] = {}
        if self.pv_tag:
            bindings["PV"] = self.pv_tag
        if self.sp_tag:
            bindings["SP"] = self.sp_tag
        if self.sp_int_tag:
            bindings["SPInt"] = self.sp_int_tag
        if self.mv_tag:
            bindings["MV"] = self.mv_tag
        return bindings


# =============================================================================
# MONITOR ASSEMBLIES (READ-ONLY)
# =============================================================================


@dataclass
class AnaMon(BaseDataAssembly):
    """Analog Monitor - read-only analog value with alarm limits.

    Monitors an analog process value and generates alarms when
    the value exceeds configured high/low limits. This is a
    read-only assembly - it cannot control the process.

    Alarm priorities:
    - HH (High-High): Critical alarm
    - H (High): Warning alarm
    - L (Low): Warning alarm
    - LL (Low-Low): Critical alarm
    """

    # Primary value
    v: float = 0.0
    v_scl_min: float = 0.0
    v_scl_max: float = 100.0
    v_unit: int = 0

    # Alarm limits
    h_limit: float = 90.0  # High limit
    hh_limit: float = 95.0  # High-high limit
    l_limit: float = 10.0  # Low limit
    ll_limit: float = 5.0  # Low-low limit

    # Alarm states
    alarm_h: bool = False
    alarm_hh: bool = False
    alarm_l: bool = False
    alarm_ll: bool = False

    @property
    def da_type(self) -> DataAssemblyType:
        return DataAssemblyType.ANA_MON

    def get_bindings(self) -> dict[str, str]:
        return {"V": self.tag_name}

    def update_alarms(self) -> None:
        """Update alarm states based on current value.

        Compares the current value against configured limits and
        sets/clears alarm flags accordingly. Alarms are level-based:
        a high-high alarm implies a high alarm is also active.
        """
        self.alarm_hh = self.v >= self.hh_limit
        self.alarm_h = self.v >= self.h_limit
        self.alarm_ll = self.v <= self.ll_limit
        self.alarm_l = self.v <= self.l_limit


@dataclass
class BinMon(BaseDataAssembly):
    """Binary Monitor - read-only binary/boolean value with state tracking.

    Monitors a binary process value and detects unexpected state errors.
    If an expected_state is configured, the monitor will set mon_state_err
    when the actual value doesn't match the expectation.
    """

    # Primary value
    v: bool = False
    v_state_0: str = "Off"  # Text for False state
    v_state_1: str = "On"  # Text for True state

    # State error detection
    mon_state_err: bool = False  # Unexpected state detected
    expected_state: bool | None = None  # Expected state (None = no expectation)

    @property
    def da_type(self) -> DataAssemblyType:
        return DataAssemblyType.BIN_MON

    def get_bindings(self) -> dict[str, str]:
        return {"V": self.tag_name}

    def update_state_error(self) -> None:
        """Update state error flag based on expected state.

        If expected_state is set and the actual value doesn't match,
        sets mon_state_err to True. Otherwise clears the error.
        """
        if self.expected_state is None:
            self.mon_state_err = False
        else:
            self.mon_state_err = self.v != self.expected_state


# Type alias for all data assembly types
DataAssembly = (
    AnaView
    | BinView
    | DIntView
    | StringView
    | AnaServParam
    | BinServParam
    | DIntServParam
    | StringServParam
    | BinVlv
    | AnaVlv
    | BinDrv
    | AnaDrv
    | PIDCtrl
    | AnaMon
    | BinMon
)


# Factory for creating data assemblies from config
DATA_ASSEMBLY_CLASSES: dict[str, type[BaseDataAssembly]] = {
    "AnaView": AnaView,
    "BinView": BinView,
    "DIntView": DIntView,
    "StringView": StringView,
    "AnaServParam": AnaServParam,
    "BinServParam": BinServParam,
    "DIntServParam": DIntServParam,
    "StringServParam": StringServParam,
    "BinVlv": BinVlv,
    "AnaVlv": AnaVlv,
    "BinDrv": BinDrv,
    "AnaDrv": AnaDrv,
    "PIDCtrl": PIDCtrl,
    "AnaMon": AnaMon,
    "BinMon": BinMon,
}


def create_data_assembly(da_type: str, name: str, tag_name: str, **kwargs: Any) -> DataAssembly:
    """Factory function to create data assemblies from configuration."""
    if da_type not in DATA_ASSEMBLY_CLASSES:
        raise ValueError(f"Unknown data assembly type: {da_type}")

    cls = DATA_ASSEMBLY_CLASSES[da_type]
    return cls(name=name, tag_name=tag_name, **kwargs)  # type: ignore[return-value]
