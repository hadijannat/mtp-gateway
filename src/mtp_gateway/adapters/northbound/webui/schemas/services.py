"""Service schemas for WebUI API.

Provides request/response models for service state and command operations.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ServiceState(str, Enum):
    """PackML service states.

    Based on ISA-88 / PackML state machine.
    """

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
    RESETTING = "RESETTING"
    SUSPENDING = "SUSPENDING"
    SUSPENDED = "SUSPENDED"
    UNSUSPENDING = "UNSUSPENDING"


class ServiceCommand(str, Enum):
    """PackML commands for service control.

    Commands trigger state transitions in the PackML state machine.
    """

    START = "START"
    STOP = "STOP"
    HOLD = "HOLD"
    UNHOLD = "UNHOLD"
    SUSPEND = "SUSPEND"
    UNSUSPEND = "UNSUSPEND"
    ABORT = "ABORT"
    CLEAR = "CLEAR"
    RESET = "RESET"


class ProcedureInfo(BaseModel):
    """Service procedure information.

    Attributes:
        id: Procedure ID
        name: Procedure name
        is_default: Whether this is the default procedure
    """

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., ge=0, description="Procedure ID")
    name: str = Field(..., description="Procedure name")
    is_default: bool = Field(default=False, description="Default procedure")


class ServiceResponse(BaseModel):
    """Service status response.

    Attributes:
        name: Service name
        state: Current PackML state
        state_time: Time in current state (ISO 8601 duration)
        procedure_id: Active procedure ID
        procedure_name: Active procedure name
        procedures: Available procedures
        interlocked: Whether service is interlocked
        interlock_reason: Interlock description if active
        mode: Proxy mode (thin/thick/hybrid)
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Service name")
    state: ServiceState = Field(..., description="Current state")
    state_time: str | None = Field(default=None, description="Time in current state")
    procedure_id: int | None = Field(default=None, description="Active procedure ID")
    procedure_name: str | None = Field(default=None, description="Active procedure name")
    procedures: list[ProcedureInfo] = Field(
        default_factory=list, description="Available procedures"
    )
    interlocked: bool = Field(default=False, description="Interlock active")
    interlock_reason: str | None = Field(default=None, description="Interlock reason")
    mode: str = Field(default="thin_proxy", description="Proxy mode")


class ServiceListResponse(BaseModel):
    """Response for service list endpoint.

    Attributes:
        services: List of service statuses
        count: Total number of services
    """

    model_config = ConfigDict(extra="forbid")

    services: list[ServiceResponse] = Field(default_factory=list, description="Service statuses")
    count: int = Field(..., ge=0, description="Total service count")


class ServiceCommandRequest(BaseModel):
    """Request to send a command to a service.

    Attributes:
        command: PackML command to send
        procedure_id: Procedure to select (optional, for START)
        parameters: Command parameters (optional)
    """

    model_config = ConfigDict(extra="forbid")

    command: ServiceCommand = Field(..., description="Command to send")
    procedure_id: int | None = Field(default=None, ge=0, description="Procedure ID")
    parameters: dict[str, float | int | bool | str] | None = Field(
        default=None,
        description="Command parameters",
    )


class ServiceCommandResponse(BaseModel):
    """Response for service command execution.

    Attributes:
        success: Whether command was accepted
        service_name: Target service name
        command: Command that was sent
        previous_state: State before command
        current_state: State after command (if transition occurred)
        message: Result message or error description
    """

    model_config = ConfigDict(extra="forbid")

    success: bool = Field(..., description="Command accepted")
    service_name: str = Field(..., description="Service name")
    command: ServiceCommand = Field(..., description="Command sent")
    previous_state: ServiceState = Field(..., description="State before command")
    current_state: ServiceState = Field(..., description="Current state")
    message: str = Field(default="", description="Result message")
