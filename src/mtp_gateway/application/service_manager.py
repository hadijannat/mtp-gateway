"""Service Manager for MTP Gateway.

Orchestrates service lifecycle, state machine execution, and completion monitoring.
Supports THIN, THICK, and HYBRID proxy modes per VDI 2658.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from mtp_gateway.config.schema import ProxyMode, ServiceConfig, WriteAction
from mtp_gateway.domain.model.services import (
    ServiceDefinition,
    ServiceRuntimeState,
)
from mtp_gateway.domain.model.tags import Quality
from mtp_gateway.domain.rules.interlocks import InterlockResult
from mtp_gateway.domain.state_machine.packml import (
    PackMLCommand,
    PackMLState,
    PackMLStateMachine,
    TransitionResult,
)

if TYPE_CHECKING:
    from mtp_gateway.adapters.persistence import PersistenceRepository
    from mtp_gateway.application.tag_manager import TagManager
    from mtp_gateway.domain.rules.interlocks import InterlockEvaluator
    from mtp_gateway.domain.rules.safety import SafetyController

logger = structlog.get_logger(__name__)


# Type alias for state change callbacks
StateChangeCallback = Callable[[str, PackMLState, PackMLState], None]


class ServiceManager:
    """Manages service lifecycle and state machine execution.

    Responsibilities:
    - Create and manage service runtime state
    - Route commands to services based on proxy mode
    - Execute state hooks via tag_manager
    - Monitor completion conditions
    - Notify subscribers of state changes
    - Sync with PLC for thin/hybrid modes

    Proxy Mode Behavior:
    | Mode   | State Machine | Command Handling        | Completion          |
    |--------|---------------|-------------------------|---------------------|
    | THIN   | In PLC        | Write to command_op_tag | Poll state_cur_tag  |
    | THICK  | In Gateway    | Execute hooks, auto-tx  | Condition or timeout|
    | HYBRID | Gateway+PLC   | Write to PLC + track    | Poll + condition    |
    """

    def __init__(
        self,
        tag_manager: TagManager,
        services: list[ServiceConfig],
        persistence: PersistenceRepository | None = None,
        safety: SafetyController | None = None,
        interlock_evaluator: InterlockEvaluator | None = None,
    ) -> None:
        """Initialize the ServiceManager.

        Args:
            tag_manager: TagManager for reading/writing tags
            services: List of service configurations
            persistence: Optional PersistenceRepository for state recovery
            safety: Optional SafetyController for emergency stop
            interlock_evaluator: Optional InterlockEvaluator for interlock checks
        """
        self._tag_manager = tag_manager
        self._persistence = persistence
        self._safety = safety
        self._interlock_evaluator = interlock_evaluator
        self._services: dict[str, ServiceRuntimeState] = {}
        self._subscribers: list[StateChangeCallback] = []
        self._completion_tasks: dict[str, asyncio.Task[None]] = {}
        self._sync_tasks: dict[str, asyncio.Task[None]] = {}
        self._background_tasks: set[asyncio.Task[object]] = set()
        self._running = False
        self._lock = asyncio.Lock()

        # Initialize services from configuration
        self._init_services(services)

    def _init_services(self, service_configs: list[ServiceConfig]) -> None:
        """Initialize service runtime state from configuration."""
        for config in service_configs:
            definition = ServiceDefinition.from_config(config)
            state_machine = PackMLStateMachine(
                name=config.name,
                initial_state=PackMLState.IDLE,
            )

            # Register state change callbacks
            self._register_state_callbacks(state_machine, definition)

            runtime = ServiceRuntimeState(
                definition=definition,
                state_machine=state_machine,
                current_procedure_id=None,
                execute_start_time=None,
                quality=Quality.GOOD,
            )

            self._services[config.name] = runtime
            logger.info(
                "Service initialized",
                service=config.name,
                mode=config.mode.value,
            )

    def _register_state_callbacks(
        self,
        state_machine: PackMLStateMachine,
        definition: ServiceDefinition,
    ) -> None:
        """Register callbacks for state transitions to execute hooks."""
        # Register on_enter callbacks for each state with hooks
        for state in PackMLState:
            hooks = definition.state_hooks.get_hooks_for_state(state)
            if hooks:

                async def on_enter_state(
                    entered_state: PackMLState,
                    hooks: tuple[WriteAction, ...] = hooks,
                    service_name: str = definition.name,
                ) -> None:
                    await self._execute_hooks(hooks)
                    logger.debug(
                        "Executed hooks for state",
                        service=service_name,
                        state=entered_state.name,
                        hook_count=len(hooks),
                    )

                state_machine.on_enter(state, on_enter_state)

    async def start(self) -> None:
        """Start the service manager.

        Starts PLC sync loops for thin/hybrid mode services.
        """
        if self._running:
            return

        self._running = True
        logger.info("Starting service manager")

        # Start sync loops for thin/hybrid services
        for name, runtime in self._services.items():
            if runtime.definition.mode in (ProxyMode.THIN, ProxyMode.HYBRID):
                task = asyncio.create_task(
                    self._plc_sync_loop(runtime),
                    name=f"sync_{name}",
                )
                self._sync_tasks[name] = task

    async def stop(self) -> None:
        """Stop the service manager.

        Cancels completion monitors and sync tasks.
        """
        if not self._running:
            return

        self._running = False
        logger.info("Stopping service manager")

        # Cancel all completion tasks
        for task in self._completion_tasks.values():
            task.cancel()
        if self._completion_tasks:
            await asyncio.gather(*self._completion_tasks.values(), return_exceptions=True)
        self._completion_tasks.clear()

        # Cancel all sync tasks
        for task in self._sync_tasks.values():
            task.cancel()
        if self._sync_tasks:
            await asyncio.gather(*self._sync_tasks.values(), return_exceptions=True)
        self._sync_tasks.clear()

        # Cancel background tasks
        for task in self._background_tasks:
            task.cancel()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
        self._background_tasks.clear()

        logger.info("Service manager stopped")

    async def emergency_stop(self) -> None:
        """Trigger emergency stop - set all outputs to safe state.

        Performs the following actions:
        1. Writes all safe state outputs from SafetyController
        2. Aborts all active services
        3. Logs emergency stop event if persistence is configured

        This method continues even if individual writes fail, ensuring
        all safe outputs are attempted.
        """
        logger.warning("Emergency stop triggered")

        # Log emergency stop event
        if self._persistence:
            await self._persistence.log_command(
                timestamp=datetime.now(UTC),
                command_type="EMERGENCY_STOP",
                target="ALL_SERVICES",
                parameters={},
                result="INITIATED",
            )

        # Write all safe state outputs
        if self._safety:
            safe_values = self._safety.get_safe_state_values()
            for tag_name, value in safe_values.items():
                try:
                    success = await self._tag_manager.write_tag(tag_name, value)
                    if not success:
                        logger.error(
                            "Failed to set safe state output",
                            tag=tag_name,
                            value=value,
                        )
                except Exception as e:
                    logger.error(
                        "Exception setting safe state output",
                        tag=tag_name,
                        error=str(e),
                    )

        # Abort all services
        for name in self._services:
            try:
                await self.send_command(name, PackMLCommand.ABORT)
            except Exception as e:
                logger.error(
                    "Failed to abort service",
                    service=name,
                    error=str(e),
                )

        logger.warning("Emergency stop completed")

    async def send_command(
        self,
        service_name: str,
        command: PackMLCommand,
        procedure_id: int | None = None,
    ) -> TransitionResult:
        """Send a command to a service.

        Routes the command based on the service's proxy mode.

        Args:
            service_name: Name of the service
            command: PackML command to execute
            procedure_id: Optional procedure ID for START command

        Returns:
            TransitionResult indicating success/failure
        """
        runtime = self._services.get(service_name)
        if runtime is None:
            return TransitionResult(
                success=False,
                from_state=PackMLState.UNDEFINED,
                to_state=None,
                error=f"Service '{service_name}' not found",
            )

        # Check interlocks before START/RESUME/UNHOLD commands
        # ABORT and STOP are NEVER blocked (safety priority)
        blocked_commands = {
            PackMLCommand.START,
            PackMLCommand.UNHOLD,
        }
        if command in blocked_commands and self._interlock_evaluator:
            interlock_result = self._check_service_interlocks(service_name)
            if interlock_result.interlocked:
                logger.warning(
                    "Command blocked by interlock",
                    service=service_name,
                    command=command.name,
                    reason=interlock_result.reason,
                )
                return TransitionResult(
                    success=False,
                    from_state=runtime.state_machine.current_state,
                    to_state=None,
                    error=interlock_result.reason or "Interlock active",
                )

        # Set procedure ID for START command
        if command == PackMLCommand.START:
            if procedure_id is not None:
                runtime.current_procedure_id = procedure_id
            else:
                # Find default procedure
                default_proc = next(
                    (p for p in runtime.definition.procedures if p.is_default),
                    None,
                )
                runtime.current_procedure_id = default_proc.id if default_proc else 0

        # Route based on proxy mode
        match runtime.definition.mode:
            case ProxyMode.THICK:
                return await self._send_command_thick(runtime, command)
            case ProxyMode.THIN:
                return await self._send_command_thin(runtime, command)
            case ProxyMode.HYBRID:
                return await self._send_command_hybrid(runtime, command)

    async def _send_command_thick(
        self, runtime: ServiceRuntimeState, command: PackMLCommand
    ) -> TransitionResult:
        """Handle command for thick proxy mode.

        State machine runs in the gateway. Hooks are executed on state entry.
        """
        from_state = runtime.state_machine.current_state

        result = await runtime.state_machine.send_command(command)

        if result.success and result.to_state:
            # Notify subscribers
            self._notify_subscribers(runtime.definition.name, from_state, result.to_state)

            # Start completion monitor if entering EXECUTE
            if result.to_state == PackMLState.EXECUTE:
                runtime.execute_start_time = datetime.now(UTC)
                self._start_completion_monitor(runtime)

            # Auto-complete acting states for thick mode
            # (hooks already executed via callbacks)
            if self._is_acting_state(result.to_state):
                await self._auto_complete_acting_state(runtime)

        return result

    async def _send_command_thin(
        self, runtime: ServiceRuntimeState, command: PackMLCommand
    ) -> TransitionResult:
        """Handle command for thin proxy mode.

        State machine runs in PLC. Write command to command_op_tag.
        """
        if runtime.definition.command_op_tag is None:
            return TransitionResult(
                success=False,
                from_state=runtime.state_machine.current_state,
                to_state=None,
                error="Thin proxy service missing command_op_tag",
            )

        from_state = runtime.state_machine.current_state

        # Write command value to PLC
        success = await self._tag_manager.write_tag(
            runtime.definition.command_op_tag, command.value
        )

        if success:
            # For thin mode, state will be updated by sync loop
            return TransitionResult(
                success=True,
                from_state=from_state,
                to_state=None,  # Unknown until sync
            )
        else:
            return TransitionResult(
                success=False,
                from_state=from_state,
                to_state=None,
                error="Failed to write command to PLC",
            )

    async def _send_command_hybrid(
        self, runtime: ServiceRuntimeState, command: PackMLCommand
    ) -> TransitionResult:
        """Handle command for hybrid proxy mode.

        Write to PLC and track state locally.
        """
        # Write to PLC like thin mode
        thin_result = await self._send_command_thin(runtime, command)

        if thin_result.success:
            # Also update local state machine for tracking
            await runtime.state_machine.send_command(command)

        return thin_result

    async def _execute_hooks(self, hooks: tuple[WriteAction, ...]) -> None:
        """Execute a sequence of write actions.

        Args:
            hooks: Tuple of WriteAction to execute
        """
        for action in hooks:
            await self._tag_manager.write_tag(action.tag, action.value)

    async def _auto_complete_acting_state(self, runtime: ServiceRuntimeState) -> None:
        """Auto-complete an acting state after hooks finish."""
        from_state = runtime.state_machine.current_state
        result = await runtime.state_machine.complete_acting_state()

        if result.success and result.to_state:
            self._notify_subscribers(runtime.definition.name, from_state, result.to_state)

            # Check if new state is also an acting state
            if self._is_acting_state(result.to_state):
                await self._auto_complete_acting_state(runtime)

            # Start completion monitor if now in EXECUTE
            if result.to_state == PackMLState.EXECUTE:
                runtime.execute_start_time = datetime.now(UTC)
                self._start_completion_monitor(runtime)

    def _is_acting_state(self, state: PackMLState) -> bool:
        """Check if state is an acting state (-ING suffix)."""
        acting_states = {
            PackMLState.STARTING,
            PackMLState.COMPLETING,
            PackMLState.HOLDING,
            PackMLState.UNHOLDING,
            PackMLState.STOPPING,
            PackMLState.ABORTING,
            PackMLState.CLEARING,
            PackMLState.SUSPENDING,
            PackMLState.UNSUSPENDING,
            PackMLState.RESETTING,
        }
        return state in acting_states

    def _start_completion_monitor(self, runtime: ServiceRuntimeState) -> None:
        """Start completion monitoring for a service in EXECUTE state."""
        # Cancel existing monitor if any
        if runtime.definition.name in self._completion_tasks:
            self._completion_tasks[runtime.definition.name].cancel()

        task = asyncio.create_task(
            self._completion_monitor_loop(runtime),
            name=f"completion_{runtime.definition.name}",
        )
        self._completion_tasks[runtime.definition.name] = task

    async def _completion_monitor_loop(self, runtime: ServiceRuntimeState) -> None:
        """Monitor for service completion.

        Checks timeout, condition, or self_completing flag.
        """
        completion = runtime.definition.completion

        try:
            while self._running:
                # Check if still in EXECUTE
                if runtime.state_machine.current_state != PackMLState.EXECUTE:
                    break

                # Self-completing: trigger COMPLETE immediately
                if completion.self_completing:
                    await self.send_command(runtime.definition.name, PackMLCommand.COMPLETE)
                    break

                # Check completion condition
                if completion.condition:
                    value = self._tag_manager.get_value(completion.condition.tag)
                    if value and completion.condition.evaluate(value.value):
                        await self.send_command(runtime.definition.name, PackMLCommand.COMPLETE)
                        break

                # Check timeout
                if completion.timeout_s and runtime.execute_start_time:
                    elapsed = (datetime.now(UTC) - runtime.execute_start_time).total_seconds()
                    if elapsed >= completion.timeout_s:
                        logger.warning(
                            "Service execution timeout",
                            service=runtime.definition.name,
                            timeout_s=completion.timeout_s,
                        )
                        # Timeout: abort the service
                        await self.send_command(runtime.definition.name, PackMLCommand.ABORT)
                        break

                # Wait before next check
                await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            pass

    async def _plc_sync_loop(self, runtime: ServiceRuntimeState) -> None:
        """Sync state from PLC for thin/hybrid mode services."""
        if runtime.definition.state_cur_tag is None:
            logger.warning(
                "Thin/hybrid service missing state_cur_tag",
                service=runtime.definition.name,
            )
            return

        try:
            while self._running:
                value = self._tag_manager.get_value(runtime.definition.state_cur_tag)
                if value and isinstance(value.value, int):
                    try:
                        plc_state = PackMLState(value.value)
                        current = runtime.state_machine.current_state
                        if plc_state != current:
                            # Update local state to match PLC
                            runtime.state_machine._state = plc_state
                            self._notify_subscribers(runtime.definition.name, current, plc_state)
                    except ValueError:
                        logger.warning(
                            "Invalid state value from PLC",
                            service=runtime.definition.name,
                            value=value.value,
                        )

                await asyncio.sleep(0.1)  # Sync interval

        except asyncio.CancelledError:
            pass

    def get_service_state(self, name: str) -> PackMLState | None:
        """Get the current state of a service.

        Args:
            name: Service name

        Returns:
            Current PackMLState or None if service not found
        """
        runtime = self._services.get(name)
        return runtime.state_machine.current_state if runtime else None

    def subscribe(self, callback: StateChangeCallback) -> None:
        """Subscribe to state change notifications.

        Args:
            callback: Function(service_name, from_state, to_state)
        """
        self._subscribers.append(callback)

    def unsubscribe(self, callback: StateChangeCallback) -> None:
        """Unsubscribe from state change notifications.

        Args:
            callback: Previously registered callback
        """
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def _notify_subscribers(
        self, service_name: str, from_state: PackMLState, to_state: PackMLState
    ) -> None:
        """Notify all subscribers of a state change and persist state."""
        # Persist state change (fire-and-forget async task)
        if self._persistence:
            runtime = self._services.get(service_name)
            if runtime:
                self._track_task(
                    asyncio.create_task(
                        self._persist_service_state(service_name, runtime),
                        name=f"persist_{service_name}",
                    )
                )

        for callback in self._subscribers:
            try:
                callback(service_name, from_state, to_state)
            except Exception as e:
                logger.warning(
                    "Subscriber callback error",
                    service=service_name,
                    error=str(e),
                )

    async def _persist_service_state(self, service_name: str, runtime: ServiceRuntimeState) -> None:
        """Persist service state to repository."""
        if not self._persistence:
            return

        try:
            await self._persistence.save_service_state(
                service_name=service_name,
                state=runtime.state_machine.current_state,
                procedure_id=runtime.current_procedure_id,
                parameters={},  # Can extend to include procedure parameters
            )
        except Exception as e:
            logger.warning(
                "Failed to persist service state",
                service=service_name,
                error=str(e),
            )

    async def recover_services(self) -> None:
        """Restore service states from persistence after restart.

        Reads persisted state snapshots and restores service state machines
        to their saved states. After recovery, clears the persisted state
        since services are now running.
        """
        if not self._persistence:
            return

        snapshots = await self._persistence.get_all_service_states()
        for snapshot in snapshots:
            runtime = self._services.get(snapshot.service_name)
            if not runtime:
                logger.warning(
                    "Persisted state for unknown service",
                    service=snapshot.service_name,
                )
                continue

            try:
                # Restore state
                restored_state = PackMLState[snapshot.state]
                runtime.state_machine._state = restored_state

                # Restore procedure ID
                if snapshot.procedure_id is not None:
                    runtime.current_procedure_id = snapshot.procedure_id

                logger.info(
                    "Service state recovered",
                    service=snapshot.service_name,
                    state=snapshot.state,
                    procedure_id=snapshot.procedure_id,
                )

                # Clear persisted state after successful recovery
                await self._persistence.delete_service_state(snapshot.service_name)

            except (KeyError, ValueError) as e:
                logger.warning(
                    "Failed to recover service state",
                    service=snapshot.service_name,
                    state=snapshot.state,
                    error=str(e),
                )

    def _check_service_interlocks(self, service_name: str) -> InterlockResult:
        """Check interlock conditions for a service.

        Collects current tag values from the tag manager and evaluates
        interlock bindings for the specified service.

        Args:
            service_name: Name of the service to check

        Returns:
            InterlockResult indicating if service is interlocked
        """
        if not self._interlock_evaluator:
            return InterlockResult(interlocked=False)

        # Collect tag values for all source tags in bindings
        tag_values: dict[str, object] = {}
        for binding in self._interlock_evaluator.bindings.values():
            tag_value = self._tag_manager.get_value(binding.source_tag)
            if tag_value is not None:
                tag_values[binding.source_tag] = tag_value.value

        return self._interlock_evaluator.check_service_interlocks(service_name, tag_values)

    def _track_task(self, task: asyncio.Task[object]) -> None:
        """Track background tasks so they aren't garbage-collected."""
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
