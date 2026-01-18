"""Service and Procedure domain models for MTP Gateway.

Defines the domain models for MTP services, procedures, and their runtime state.
These models are used by the ServiceManager to execute service lifecycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

from mtp_gateway.config.schema import (
    ComparisonOp,
    CompletionConfig,
    ProcedureConfig,
    ProxyMode,
    ServiceConfig,
    StateHooksConfig,
    StateTimeoutsConfig,
    TimeoutAction,
    WriteAction,
)
from mtp_gateway.domain.state_machine.packml import PackMLState, PackMLStateMachine

if TYPE_CHECKING:
    from mtp_gateway.domain.model.tags import Quality


@dataclass(frozen=True, slots=True)
class ProcedureParameter:
    """Parameter for a service procedure.

    Attributes:
        name: Parameter name
        data_assembly: Reference to the data assembly providing the parameter
        required: Whether the parameter must be set before starting
    """

    name: str
    data_assembly: str
    required: bool = False


@dataclass(frozen=True, slots=True)
class ProcedureDefinition:
    """Definition of a service procedure.

    A service can have multiple procedures (operational modes).
    One procedure is typically the default.

    Attributes:
        id: Procedure ID (0-based index)
        name: Procedure name
        is_default: Whether this is the default procedure
        parameters: Tuple of procedure-specific parameters
    """

    id: int
    name: str
    is_default: bool = False
    parameters: tuple[ProcedureParameter, ...] = ()

    @classmethod
    def from_config(cls, config: ProcedureConfig) -> ProcedureDefinition:
        """Create ProcedureDefinition from configuration.

        Args:
            config: Procedure configuration from YAML

        Returns:
            Immutable ProcedureDefinition domain model
        """
        parameters = tuple(
            ProcedureParameter(
                name=p.name,
                data_assembly=p.data_assembly,
                required=p.required,
            )
            for p in config.parameters
        )
        return cls(
            id=config.id,
            name=config.name,
            is_default=config.is_default,
            parameters=parameters,
        )


@dataclass(frozen=True, slots=True)
class CompletionCondition:
    """Condition for service completion detection.

    Attributes:
        tag: Tag to evaluate
        operator: Comparison operator
        reference: Reference value for comparison
    """

    tag: str
    operator: ComparisonOp
    reference: float | int | bool | str

    def evaluate(self, current_value: float | int | bool | str) -> bool:
        """Evaluate the condition against a current value.

        Args:
            current_value: Current value of the tag

        Returns:
            True if condition is satisfied
        """
        match self.operator:
            case ComparisonOp.EQ:
                return current_value == self.reference
            case ComparisonOp.NE:
                return current_value != self.reference
            case ComparisonOp.GT:
                return current_value > self.reference  # type: ignore[operator]
            case ComparisonOp.GE:
                return current_value >= self.reference  # type: ignore[operator]
            case ComparisonOp.LT:
                return current_value < self.reference  # type: ignore[operator]
            case ComparisonOp.LE:
                return current_value <= self.reference  # type: ignore[operator]
            case _:
                # Exhaustive match - should never reach here
                raise ValueError(f"Unknown operator: {self.operator}")


@dataclass(frozen=True, slots=True)
class StateHooks:
    """State transition hooks for service execution.

    Each hook contains actions to execute when entering the corresponding state.
    Actions are typically tag writes to the PLC.

    Attributes:
        on_starting: Actions when entering STARTING state
        on_execute: Actions when entering EXECUTE state
        on_completing: Actions when entering COMPLETING state
        on_completed: Actions when entering COMPLETED state
        on_stopping: Actions when entering STOPPING state
        on_stopped: Actions when entering STOPPED state
        on_aborting: Actions when entering ABORTING state
        on_aborted: Actions when entering ABORTED state
        on_holding: Actions when entering HOLDING state
        on_held: Actions when entering HELD state
        on_unholding: Actions when entering UNHOLDING state
        on_resetting: Actions when entering RESETTING state
    """

    on_starting: tuple[WriteAction, ...]
    on_execute: tuple[WriteAction, ...]
    on_completing: tuple[WriteAction, ...]
    on_completed: tuple[WriteAction, ...]
    on_stopping: tuple[WriteAction, ...]
    on_stopped: tuple[WriteAction, ...]
    on_aborting: tuple[WriteAction, ...]
    on_aborted: tuple[WriteAction, ...]
    on_holding: tuple[WriteAction, ...]
    on_held: tuple[WriteAction, ...]
    on_unholding: tuple[WriteAction, ...]
    on_resetting: tuple[WriteAction, ...]

    def get_hooks_for_state(self, state: PackMLState) -> tuple[WriteAction, ...]:
        """Get the hooks for a given state.

        Args:
            state: PackML state to get hooks for

        Returns:
            Tuple of WriteAction to execute for the state
        """
        mapping: dict[PackMLState, tuple[WriteAction, ...]] = {
            PackMLState.STARTING: self.on_starting,
            PackMLState.EXECUTE: self.on_execute,
            PackMLState.COMPLETING: self.on_completing,
            PackMLState.COMPLETED: self.on_completed,
            PackMLState.STOPPING: self.on_stopping,
            PackMLState.STOPPED: self.on_stopped,
            PackMLState.ABORTING: self.on_aborting,
            PackMLState.ABORTED: self.on_aborted,
            PackMLState.HOLDING: self.on_holding,
            PackMLState.HELD: self.on_held,
            PackMLState.UNHOLDING: self.on_unholding,
            PackMLState.RESETTING: self.on_resetting,
        }
        return mapping.get(state, ())

    @classmethod
    def from_config(cls, config: StateHooksConfig) -> StateHooks:
        """Create StateHooks from configuration.

        Args:
            config: State hooks configuration from YAML

        Returns:
            Immutable StateHooks domain model
        """
        return cls(
            on_starting=tuple(config.on_starting),
            on_execute=tuple(config.on_execute),
            on_completing=tuple(config.on_completing),
            on_completed=tuple(config.on_completed),
            on_stopping=tuple(config.on_stopping),
            on_stopped=tuple(config.on_stopped),
            on_aborting=tuple(config.on_aborting),
            on_aborted=tuple(config.on_aborted),
            on_holding=tuple(config.on_holding),
            on_held=tuple(config.on_held),
            on_unholding=tuple(config.on_unholding),
            on_resetting=tuple(config.on_resetting),
        )


@dataclass(frozen=True, slots=True)
class CompletionSpec:
    """Service completion detection configuration.

    Attributes:
        self_completing: Service auto-completes when EXECUTE ends
        condition: Tag condition for completion
        timeout_s: Timeout for completion in seconds
    """

    self_completing: bool
    condition: CompletionCondition | None
    timeout_s: float | None

    @classmethod
    def from_config(cls, config: CompletionConfig) -> CompletionSpec:
        """Create CompletionSpec from configuration.

        Args:
            config: Completion configuration from YAML

        Returns:
            Immutable CompletionSpec domain model
        """
        condition = None
        if config.condition is not None:
            condition = CompletionCondition(
                tag=config.condition.tag,
                operator=config.condition.op,
                reference=config.condition.ref,
            )

        return cls(
            self_completing=config.self_completing,
            condition=condition,
            timeout_s=config.timeout_s,
        )


@dataclass(frozen=True, slots=True)
class StateTimeoutSpec:
    """Timeout configuration for service states."""

    auto_complete_acting_states: bool
    timeouts: dict[PackMLState, float]
    on_timeout: TimeoutAction

    @classmethod
    def from_config(cls, config: StateTimeoutsConfig) -> StateTimeoutSpec:
        """Create StateTimeoutSpec from configuration."""
        timeouts = {
            PackMLState[state_name.value]: timeout
            for state_name, timeout in config.timeouts.items()
        }
        return cls(
            auto_complete_acting_states=config.auto_complete_acting_states,
            timeouts=timeouts,
            on_timeout=config.on_timeout,
        )


@dataclass(frozen=True, slots=True)
class ActingStateCondition:
    """Condition to advance an acting state."""

    state: PackMLState
    condition: CompletionCondition


@dataclass(frozen=True, slots=True)
class ServiceDefinition:
    """Definition of an MTP service.

    A service encapsulates a unit operation with PackML state machine,
    procedures, parameters, and completion logic.

    Attributes:
        name: Service name
        mode: Proxy mode (THIN, THICK, HYBRID)
        procedures: Available procedures for the service
        parameters: Service-level parameters
        state_hooks: Actions to execute on state transitions
        completion: Completion detection configuration
        state_cur_tag: Tag for current state (thin proxy)
        command_op_tag: Tag for command operation (thin proxy)
    """

    name: str
    mode: ProxyMode
    procedures: tuple[ProcedureDefinition, ...]
    parameters: tuple[ProcedureParameter, ...]
    state_hooks: StateHooks
    completion: CompletionSpec
    timeouts: StateTimeoutSpec
    acting_state_conditions: tuple[ActingStateCondition, ...]
    state_cur_tag: str | None
    command_op_tag: str | None

    @classmethod
    def from_config(cls, config: ServiceConfig) -> ServiceDefinition:
        """Create ServiceDefinition from configuration.

        Args:
            config: Service configuration from YAML

        Returns:
            Immutable ServiceDefinition domain model
        """
        procedures = tuple(ProcedureDefinition.from_config(p) for p in config.procedures)

        parameters = tuple(
            ProcedureParameter(
                name=p.name,
                data_assembly=p.data_assembly,
                required=p.required,
            )
            for p in config.parameters
        )
        acting_conditions = tuple(
            ActingStateCondition(
                state=PackMLState[state_name.value],
                condition=CompletionCondition(
                    tag=condition.tag,
                    operator=condition.op,
                    reference=condition.ref,
                ),
            )
            for state_name, condition in config.acting_state_conditions.items()
        )

        return cls(
            name=config.name,
            mode=config.mode,
            procedures=procedures,
            parameters=parameters,
            state_hooks=StateHooks.from_config(config.state_hooks),
            completion=CompletionSpec.from_config(config.completion),
            timeouts=StateTimeoutSpec.from_config(config.timeouts),
            acting_state_conditions=acting_conditions,
            state_cur_tag=config.state_cur_tag,
            command_op_tag=config.command_op_tag,
        )


@dataclass(slots=True)
class ServiceRuntimeState:
    """Mutable runtime state for a service.

    Tracks the current operational state of a service during execution.

    Attributes:
        definition: Immutable service definition
        state_machine: PackML state machine instance
        current_procedure_id: Currently active procedure (None if no procedure selected)
        execute_start_time: When EXECUTE state was entered (for timeout)
        quality: Current quality of the service
    """

    definition: ServiceDefinition
    state_machine: PackMLStateMachine
    current_procedure_id: int | None
    execute_start_time: datetime | None
    quality: Quality
