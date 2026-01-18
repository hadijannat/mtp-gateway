"""Configuration schema for MTP Gateway.

Uses Pydantic v2 for validation, serialization, and documentation.
Configuration is loaded from YAML files and validated against these models.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path  # noqa: TC003
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# =============================================================================
# ENUMERATIONS
# =============================================================================


class ConnectorType(str, Enum):
    """Supported southbound connector protocols."""

    MODBUS_TCP = "modbus_tcp"
    MODBUS_RTU = "modbus_rtu"
    S7 = "s7"
    EIP = "eip"  # EtherNet/IP
    OPCUA_CLIENT = "opcua_client"


class DataTypeConfig(str, Enum):
    """Supported data types in configuration."""

    BOOL = "bool"
    INT16 = "int16"
    UINT16 = "uint16"
    INT32 = "int32"
    UINT32 = "uint32"
    INT64 = "int64"
    UINT64 = "uint64"
    FLOAT32 = "float32"
    FLOAT64 = "float64"
    STRING = "string"


class ProxyMode(str, Enum):
    """Service proxy modes per VDI 2658."""

    THIN = "thin_proxy"  # State machine in PLC
    THICK = "thick_proxy"  # State machine in Gateway
    HYBRID = "hybrid"  # Split state machine


class PackMLStateName(str, Enum):
    """PackML state names for configuration."""

    UNDEFINED = "UNDEFINED"
    IDLE = "IDLE"
    STARTING = "STARTING"
    EXECUTE = "EXECUTE"
    COMPLETING = "COMPLETING"
    COMPLETED = "COMPLETED"
    HOLDING = "HOLDING"
    HELD = "HELD"
    UNHOLDING = "UNHOLDING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    ABORTING = "ABORTING"
    ABORTED = "ABORTED"
    CLEARING = "CLEARING"
    SUSPENDING = "SUSPENDING"
    SUSPENDED = "SUSPENDED"
    UNSUSPENDING = "UNSUSPENDING"
    RESETTING = "RESETTING"


class TimeoutAction(str, Enum):
    """Action to take when a transition times out."""

    NONE = "none"
    ABORT = "abort"
    STOP = "stop"
    HOLD = "hold"


class CommLossAction(str, Enum):
    """Action to take when communication loss is detected."""

    NONE = "none"
    SAFE_STATE = "safe_state"
    ABORT_SERVICES = "abort_services"


class SecurityPolicy(str, Enum):
    """OPC UA security policies."""

    NONE = "None"
    BASIC128RSA15_SIGN = "Basic128Rsa15_Sign"
    BASIC128RSA15_SIGN_ENCRYPT = "Basic128Rsa15_SignAndEncrypt"
    BASIC256_SIGN = "Basic256_Sign"
    BASIC256_SIGN_ENCRYPT = "Basic256_SignAndEncrypt"
    BASIC256SHA256_SIGN = "Basic256Sha256_Sign"
    BASIC256SHA256_SIGN_ENCRYPT = "Basic256Sha256_SignAndEncrypt"


class ComparisonOp(str, Enum):
    """Comparison operators for conditions."""

    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GE = "ge"
    LT = "lt"
    LE = "le"


class ByteOrder(str, Enum):
    """Byte order for multi-byte values."""

    BIG = "big"
    LITTLE = "little"


class WordOrder(str, Enum):
    """Word order for multi-register values."""

    BIG = "big"
    LITTLE = "little"


# =============================================================================
# BASE CONFIGURATION MODELS
# =============================================================================


class GatewayInfo(BaseModel):
    """Basic gateway identification."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=64, description="Gateway instance name")
    version: str = Field(default="1.0.0", description="Gateway version")
    description: str = Field(default="", max_length=500)
    vendor: str = Field(default="", max_length=128, description="Vendor or organization name")
    vendor_url: str = Field(default="", max_length=256, description="Vendor website URL")


class RuntimePolicyConfig(BaseModel):
    """Runtime policies for failure handling and recovery."""

    model_config = ConfigDict(extra="forbid")

    comm_loss_action: CommLossAction = Field(
        default=CommLossAction.NONE,
        description="Action to take when connector communication is lost",
    )
    comm_loss_grace_s: float = Field(
        default=5.0,
        ge=0.0,
        description="Seconds of tolerated comm loss before action triggers",
    )


class OPCUASecurityConfig(BaseModel):
    """OPC UA server security configuration."""

    model_config = ConfigDict(extra="forbid")

    allow_none: bool = Field(default=False, description="Allow no-security connections")
    policies: list[SecurityPolicy] = Field(
        default_factory=lambda: [SecurityPolicy.BASIC256SHA256_SIGN_ENCRYPT],
        description="Enabled security policies",
    )
    cert_path: Path | None = Field(default=None, description="Path to server certificate")
    key_path: Path | None = Field(default=None, description="Path to private key")
    trust_list_path: Path | None = Field(default=None, description="Path to trusted certificates")


class OPCUAConfig(BaseModel):
    """OPC UA server configuration."""

    model_config = ConfigDict(extra="forbid")

    endpoint: str = Field(
        default="opc.tcp://0.0.0.0:4840",
        description="OPC UA server endpoint URL",
    )
    namespace_uri: str = Field(
        default="urn:mtp-gateway:opcua",
        description="Server namespace URI",
    )
    application_name: str = Field(default="MTP Gateway", description="OPC UA application name")
    security: OPCUASecurityConfig = Field(default_factory=OPCUASecurityConfig)


# =============================================================================
# CONNECTOR CONFIGURATION
# =============================================================================


class BaseConnectorConfig(BaseModel):
    """Base configuration for all connectors."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, description="Unique connector name")
    enabled: bool = Field(default=True, description="Whether connector is active")
    poll_interval_ms: int = Field(
        default=1000,
        ge=10,
        le=60000,
        description="Tag polling interval in milliseconds",
    )
    timeout_ms: int = Field(
        default=5000,
        ge=100,
        le=60000,
        description="Communication timeout",
    )
    retry_count: int = Field(default=3, ge=0, le=10, description="Retry attempts on failure")
    retry_delay_ms: int = Field(default=1000, ge=100, description="Delay between retries")


class ModbusTCPConnectorConfig(BaseConnectorConfig):
    """Modbus TCP connector configuration."""

    type: Literal[ConnectorType.MODBUS_TCP] = ConnectorType.MODBUS_TCP
    host: str = Field(..., description="PLC hostname or IP address")
    port: int = Field(default=502, ge=1, le=65535, description="Modbus TCP port")
    unit_id: int = Field(default=1, ge=0, le=255, description="Modbus unit/slave ID")


class ModbusRTUConnectorConfig(BaseConnectorConfig):
    """Modbus RTU (serial) connector configuration."""

    type: Literal[ConnectorType.MODBUS_RTU] = ConnectorType.MODBUS_RTU
    port: str = Field(..., description="Serial port (e.g., /dev/ttyUSB0, COM1)")
    baudrate: int = Field(default=9600, description="Serial baud rate")
    parity: Literal["N", "E", "O"] = Field(default="N", description="Parity: N/E/O")
    stopbits: Literal[1, 2] = Field(default=1)
    bytesize: Literal[7, 8] = Field(default=8)
    unit_id: int = Field(default=1, ge=0, le=255)


class S7ConnectorConfig(BaseConnectorConfig):
    """Siemens S7 connector configuration."""

    type: Literal[ConnectorType.S7] = ConnectorType.S7
    host: str = Field(..., description="PLC hostname or IP address")
    rack: int = Field(default=0, ge=0, le=7)
    slot: int = Field(default=1, ge=0, le=31)
    port: int = Field(default=102, ge=1, le=65535)


class EIPConnectorConfig(BaseConnectorConfig):
    """EtherNet/IP connector configuration."""

    type: Literal[ConnectorType.EIP] = ConnectorType.EIP
    host: str = Field(..., description="PLC hostname or IP address")
    slot: int = Field(default=0, ge=0, description="Processor slot")


class OPCUAClientConnectorConfig(BaseConnectorConfig):
    """OPC UA Client connector configuration."""

    type: Literal[ConnectorType.OPCUA_CLIENT] = ConnectorType.OPCUA_CLIENT
    endpoint: str = Field(..., description="OPC UA server endpoint URL")
    security_policy: SecurityPolicy = Field(default=SecurityPolicy.NONE)
    username: str | None = Field(default=None)
    password: str | None = Field(default=None)
    cert_path: Path | None = Field(default=None)
    key_path: Path | None = Field(default=None)


# Union of all connector types
ConnectorConfig = Annotated[
    ModbusTCPConnectorConfig
    | ModbusRTUConnectorConfig
    | S7ConnectorConfig
    | EIPConnectorConfig
    | OPCUAClientConnectorConfig,
    Field(discriminator="type"),
]


# =============================================================================
# TAG CONFIGURATION
# =============================================================================


class ScaleConfigModel(BaseModel):
    """Linear scaling configuration."""

    model_config = ConfigDict(extra="forbid")

    gain: float = Field(default=1.0, description="Scale multiplier")
    offset: float = Field(default=0.0, description="Scale offset")


class TagConfig(BaseModel):
    """Configuration for a single tag mapping."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, description="Unique tag name")
    connector: str = Field(..., description="Reference to connector name")
    address: str = Field(..., description="Protocol-specific address")
    datatype: DataTypeConfig = Field(..., description="Data type")
    byte_order: ByteOrder = Field(
        default=ByteOrder.BIG,
        description="Byte order for multi-byte values (Modbus)",
    )
    word_order: WordOrder = Field(
        default=WordOrder.BIG,
        description="Word order for multi-register values (Modbus)",
    )
    writable: bool = Field(default=False, description="Allow writes")
    scale: ScaleConfigModel | None = Field(default=None, description="Linear scaling")
    unit: str = Field(default="", max_length=32, description="Engineering unit")
    description: str = Field(default="", max_length=500)

    @field_validator("address")
    @classmethod
    def validate_address(cls, v: str) -> str:
        """Basic address validation - protocol-specific validation happens in driver."""
        if not v.strip():
            raise ValueError("Address cannot be empty")
        return v.strip()


# =============================================================================
# MTP CONFIGURATION
# =============================================================================


class DataAssemblyBindings(BaseModel):
    """Tag bindings for a data assembly."""

    model_config = ConfigDict(extra="allow")  # Allow arbitrary binding names

    v: str | None = Field(default=None, alias="V", description="Primary value tag")


class MonitorLimitsConfig(BaseModel):
    """Configuration for analog monitor alarm limits.

    Optional configuration for AnaMon data assemblies to define
    alarm thresholds. Any limit not specified will use the
    data assembly's default values.
    """

    model_config = ConfigDict(extra="forbid")

    h_limit: float | None = Field(default=None, description="High limit")
    hh_limit: float | None = Field(default=None, description="High-high limit")
    l_limit: float | None = Field(default=None, description="Low limit")
    ll_limit: float | None = Field(default=None, description="Low-low limit")


class InterlockBindingConfig(BaseModel):
    """Configuration for interlock source binding.

    Binds an active element to a source tag that determines its
    interlock state. When the condition evaluates to True, the
    element is considered interlocked and cannot execute
    START/RESUME/UNHOLD commands.
    """

    model_config = ConfigDict(extra="forbid")

    source_tag: str = Field(..., description="Tag that provides interlock state")
    condition: ComparisonOp = Field(
        default=ComparisonOp.EQ,
        description="Comparison operator",
    )
    ref_value: float | int | bool | str = Field(
        default=True,
        description="Value that triggers interlock",
    )


class DataAssemblyConfig(BaseModel):
    """Configuration for an MTP data assembly."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, description="Data assembly name")
    type: str = Field(
        ...,
        description="Assembly type (AnaView, BinView, AnaServParam, etc.)",
    )
    bindings: dict[str, str] = Field(
        default_factory=dict,
        description="Tag bindings (V, VFbk, etc.)",
    )
    description: str = Field(default="")

    # Type-specific attributes stored as extra fields
    v_scl_min: float | None = Field(default=None)
    v_scl_max: float | None = Field(default=None)
    v_unit: int | None = Field(default=None)
    v_state_0: str | None = Field(default=None)
    v_state_1: str | None = Field(default=None)

    # Phase 9: Monitor limits for AnaMon
    monitor_limits: MonitorLimitsConfig | None = Field(
        default=None,
        description="Alarm limits for analog monitors",
    )

    # Phase 9: Interlock binding for active elements
    interlock_binding: InterlockBindingConfig | None = Field(
        default=None,
        description="Interlock source binding",
    )


class WriteAction(BaseModel):
    """Action to write a value to a tag."""

    model_config = ConfigDict(extra="forbid")

    tag: str = Field(..., description="Tag to write")
    value: float | int | bool | str = Field(..., description="Value to write")


class ConditionConfig(BaseModel):
    """Condition for completion detection."""

    model_config = ConfigDict(extra="forbid")

    tag: str = Field(..., description="Tag to evaluate")
    op: ComparisonOp = Field(..., description="Comparison operator")
    ref: float | int | bool | str = Field(..., description="Reference value")


class StateHooksConfig(BaseModel):
    """State transition hooks for service execution."""

    model_config = ConfigDict(extra="forbid")

    on_starting: list[WriteAction] = Field(default_factory=list)
    on_execute: list[WriteAction] = Field(default_factory=list)
    on_completing: list[WriteAction] = Field(default_factory=list)
    on_completed: list[WriteAction] = Field(default_factory=list)
    on_stopping: list[WriteAction] = Field(default_factory=list)
    on_stopped: list[WriteAction] = Field(default_factory=list)
    on_aborting: list[WriteAction] = Field(default_factory=list)
    on_aborted: list[WriteAction] = Field(default_factory=list)
    on_holding: list[WriteAction] = Field(default_factory=list)
    on_held: list[WriteAction] = Field(default_factory=list)
    on_unholding: list[WriteAction] = Field(default_factory=list)
    on_resetting: list[WriteAction] = Field(default_factory=list)


class CompletionConfig(BaseModel):
    """Service completion detection configuration."""

    model_config = ConfigDict(extra="forbid")

    self_completing: bool = Field(
        default=False,
        description="Service auto-completes when Execute ends",
    )
    condition: ConditionConfig | None = Field(
        default=None,
        description="Tag condition for completion",
    )
    timeout_s: float | None = Field(
        default=None,
        ge=0,
        description="Timeout for completion in seconds",
    )


class StateTimeoutsConfig(BaseModel):
    """Timeouts and actions for service state execution."""

    model_config = ConfigDict(extra="forbid")

    auto_complete_acting_states: bool = Field(
        default=True,
        description="Auto-complete acting states when no conditions are configured",
    )
    timeouts: dict[PackMLStateName, float] = Field(
        default_factory=dict,
        description="Timeouts per PackML state in seconds",
    )
    on_timeout: TimeoutAction = Field(
        default=TimeoutAction.ABORT,
        description="Action to take when a timeout expires",
    )


class ServiceParameterConfig(BaseModel):
    """Service procedure parameter configuration."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Parameter name")
    data_assembly: str = Field(..., description="Reference to data assembly")
    required: bool = Field(default=False)


class ProcedureConfig(BaseModel):
    """Service procedure configuration."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., ge=0, description="Procedure ID")
    name: str = Field(..., description="Procedure name")
    is_default: bool = Field(default=False)
    parameters: list[ServiceParameterConfig] = Field(default_factory=list)


class ServiceConfig(BaseModel):
    """Configuration for an MTP service."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, description="Service name")
    mode: ProxyMode = Field(default=ProxyMode.THIN, description="Proxy mode")
    procedures: list[ProcedureConfig] = Field(
        default_factory=list,
        description="Service procedures",
    )
    parameters: list[ServiceParameterConfig] = Field(
        default_factory=list,
        description="Service-level parameters",
    )
    report_values: list[str] = Field(
        default_factory=list,
        description="Report value data assembly references",
    )
    state_hooks: StateHooksConfig = Field(default_factory=StateHooksConfig)
    completion: CompletionConfig = Field(default_factory=CompletionConfig)
    timeouts: StateTimeoutsConfig = Field(default_factory=StateTimeoutsConfig)
    acting_state_conditions: dict[PackMLStateName, ConditionConfig] = Field(
        default_factory=dict,
        description="Conditions that advance acting states (STARTING, COMPLETING, etc.)",
    )

    # State tag bindings for thin proxy mode
    state_cur_tag: str | None = Field(default=None, description="Current state tag")
    command_op_tag: str | None = Field(default=None, description="Command operation tag")


class MTPConfig(BaseModel):
    """MTP-specific configuration."""

    model_config = ConfigDict(extra="forbid")

    data_assemblies: list[DataAssemblyConfig] = Field(default_factory=list)
    services: list[ServiceConfig] = Field(default_factory=list)


# =============================================================================
# SAFETY CONFIGURATION
# =============================================================================


class SafeStateOutput(BaseModel):
    """Safe state output for emergency stop."""

    model_config = ConfigDict(extra="forbid")

    tag: str = Field(..., description="Tag to set")
    value: float | int | bool | str = Field(..., description="Safe value")


class SafetyConfig(BaseModel):
    """Safety and security configuration."""

    model_config = ConfigDict(extra="forbid")

    write_allowlist: list[str] = Field(
        default_factory=list,
        description="Tags allowed for write operations",
    )
    safe_state_outputs: list[SafeStateOutput] = Field(
        default_factory=list,
        description="Outputs to set on safety trip",
    )
    command_rate_limit: str = Field(
        default="10/s",
        description="Maximum command rate (e.g., '10/s', '100/m')",
    )


# =============================================================================
# ROOT CONFIGURATION
# =============================================================================


class GatewayConfig(BaseModel):
    """Root configuration model for MTP Gateway."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="1.0.0",
        description="Configuration schema version",
    )
    gateway: GatewayInfo
    opcua: OPCUAConfig = Field(default_factory=OPCUAConfig)
    runtime: RuntimePolicyConfig = Field(default_factory=RuntimePolicyConfig)
    connectors: list[ConnectorConfig] = Field(default_factory=list)
    tags: list[TagConfig] = Field(default_factory=list)
    mtp: MTPConfig = Field(default_factory=MTPConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)

    @model_validator(mode="after")
    def validate_references(self) -> GatewayConfig:
        """Validate that all references are valid."""
        connector_names, tag_names, da_names = self._reference_sets()
        self._validate_tag_connectors(connector_names)
        self._validate_data_assembly_bindings(tag_names)
        self._validate_service_references(tag_names, da_names)
        self._validate_write_allowlist(tag_names)
        self._validate_safe_state_outputs()
        return self

    def _reference_sets(self) -> tuple[set[str], set[str], set[str]]:
        """Build lookup sets for cross-reference validation."""
        connector_names = {connector.name for connector in self.connectors}
        tag_names = {tag.name for tag in self.tags}
        da_names = {da.name for da in self.mtp.data_assemblies}
        return connector_names, tag_names, da_names

    def _validate_tag_connectors(self, connector_names: set[str]) -> None:
        """Validate that tags reference known connectors."""
        for tag in self.tags:
            if tag.connector not in connector_names:
                raise ValueError(f"Tag '{tag.name}' references unknown connector '{tag.connector}'")

    def _validate_data_assembly_bindings(self, tag_names: set[str]) -> None:
        """Validate that data assembly bindings reference known tags."""
        for da in self.mtp.data_assemblies:
            for binding_name, tag_ref in da.bindings.items():
                if tag_ref not in tag_names:
                    raise ValueError(
                        f"Data assembly '{da.name}' binding '{binding_name}' "
                        f"references unknown tag '{tag_ref}'"
                    )

    def _validate_service_references(self, tag_names: set[str], da_names: set[str]) -> None:
        """Validate service parameter and condition references."""
        for service in self.mtp.services:
            for param in service.parameters:
                if param.data_assembly not in da_names:
                    raise ValueError(
                        f"Service '{service.name}' parameter '{param.name}' "
                        f"references unknown data assembly '{param.data_assembly}'"
                    )
            if service.completion.condition and service.completion.condition.tag not in tag_names:
                raise ValueError(
                    f"Service '{service.name}' completion condition "
                    f"references unknown tag '{service.completion.condition.tag}'"
                )
            for condition in service.acting_state_conditions.values():
                if condition.tag not in tag_names:
                    raise ValueError(
                        f"Service '{service.name}' acting state condition "
                        f"references unknown tag '{condition.tag}'"
                    )

    def _validate_write_allowlist(self, tag_names: set[str]) -> None:
        """Validate write allowlist references."""
        for tag_name in self.safety.write_allowlist:
            if tag_name not in tag_names:
                raise ValueError(f"Write allowlist references unknown tag '{tag_name}'")

    def _validate_safe_state_outputs(self) -> None:
        """Ensure safe state outputs are explicitly allowlisted."""
        for output in self.safety.safe_state_outputs:
            if output.tag not in self.safety.write_allowlist:
                raise ValueError(
                    f"Safe state output '{output.tag}' must be included in write allowlist"
                )
