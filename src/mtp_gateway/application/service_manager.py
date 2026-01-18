"""Service Manager for MTP Gateway.

Orchestrates service lifecycle, completion monitoring, and audit logging.
Delegates command execution to proxy adapters based on service mode.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from mtp_gateway.application.audit import AuditTrail
from mtp_gateway.application.proxies import ServiceProxy, create_proxy
from mtp_gateway.config.schema import ProxyMode, ServiceConfig, TimeoutAction
from mtp_gateway.domain.model.services import ServiceDefinition
from mtp_gateway.domain.model.tags import Quality
from mtp_gateway.domain.rules.interlocks import InterlockResult
from mtp_gateway.domain.state_machine.packml import (
    PackMLCommand,
    PackMLState,
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
    """Manages service lifecycle and orchestrates command execution.

    Uses proxy adapters (THIN/THICK/HYBRID) for mode-specific command handling.
    Provides interlock enforcement, completion monitoring, and audit logging.
    """

    def __init__(
        self,
        tag_manager: TagManager,
        services: list[ServiceConfig],
        persistence: PersistenceRepository | None = None,
        safety: SafetyController | None = None,
        interlock_evaluator: InterlockEvaluator | None = None,
        audit_trail: AuditTrail | None = None,
    ) -> None:
        """Initialize the ServiceManager.

        Args:
            tag_manager: TagManager for reading/writing tags.
            services: List of service configurations.
            persistence: Optional PersistenceRepository for state recovery.
            safety: Optional SafetyController for emergency stop.
            interlock_evaluator: Optional InterlockEvaluator for interlock checks.
            audit_trail: Optional AuditTrail for command/transition logging.
        """
        self._tag_manager = tag_manager
        self._persistence = persistence
        self._safety = safety
        self._interlock_evaluator = interlock_evaluator
        self._audit = audit_trail or AuditTrail()
        self._proxies: dict[str, ServiceProxy] = {}
        self._definitions: dict[str, ServiceDefinition] = {}
        self._procedure_ids: dict[str, int | None] = {}
        self._execute_start_times: dict[str, datetime | None] = {}
        self._subscribers: list[StateChangeCallback] = []
        self._completion_tasks: dict[str, asyncio.Task[None]] = {}
        self._sync_tasks: dict[str, asyncio.Task[None]] = {}
        self._state_monitor_tasks: dict[str, asyncio.Task[None]] = {}
        self._state_entry_times: dict[str, datetime] = {}
        self._background_tasks: set[asyncio.Task[object]] = set()
        self._running = False

        self._init_services(services)

    def _init_services(self, configs: list[ServiceConfig]) -> None:
        """Initialize proxies and definitions from configuration."""
        for config in configs:
            self._proxies[config.name] = create_proxy(config, self._tag_manager)
            self._definitions[config.name] = ServiceDefinition.from_config(config)
            self._procedure_ids[config.name] = None
            self._execute_start_times[config.name] = None
            logger.info("Service initialized", service=config.name, mode=config.mode.value)

    async def start(self) -> None:
        """Start the service manager and PLC sync loops for thin/hybrid services."""
        if self._running:
            return
        self._running = True
        logger.info("Starting service manager")

        for name, defn in self._definitions.items():
            if defn.mode in (ProxyMode.THIN, ProxyMode.HYBRID):
                task = asyncio.create_task(self._plc_sync_loop(name), name=f"sync_{name}")
                self._sync_tasks[name] = task
            if defn.mode in (ProxyMode.THICK, ProxyMode.HYBRID):
                task = asyncio.create_task(self._state_monitor_loop(name), name=f"monitor_{name}")
                self._state_monitor_tasks[name] = task

    async def stop(self) -> None:
        """Stop the service manager, cancelling all background tasks."""
        if not self._running:
            return
        self._running = False
        logger.info("Stopping service manager")

        for task_dict in (self._completion_tasks, self._sync_tasks):
            for t in task_dict.values():
                t.cancel()
            if task_dict:
                await asyncio.gather(*task_dict.values(), return_exceptions=True)
            task_dict.clear()

        if self._state_monitor_tasks:
            for t in self._state_monitor_tasks.values():
                t.cancel()
            await asyncio.gather(*self._state_monitor_tasks.values(), return_exceptions=True)
            self._state_monitor_tasks.clear()

        for bg_task in self._background_tasks:
            bg_task.cancel()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
        self._background_tasks.clear()

    async def emergency_stop(self) -> None:
        """Trigger emergency stop - set all outputs to safe state and abort services."""
        logger.warning("Emergency stop triggered")

        if self._persistence:
            await self._persistence.log_command(
                timestamp=datetime.now(UTC),
                command_type="EMERGENCY_STOP",
                target="ALL_SERVICES",
                parameters={},
                result="INITIATED",
            )

        if self._safety:
            for tag_name, value in self._safety.get_safe_state_values().items():
                try:
                    if not await self._tag_manager.write_tag(tag_name, value):
                        logger.error("Failed to set safe state output", tag=tag_name)
                except Exception as e:
                    logger.error("Exception setting safe state output", tag=tag_name, error=str(e))

        for name in self._proxies:
            try:
                await self.send_command(name, PackMLCommand.ABORT)
            except Exception as e:
                logger.error("Failed to abort service", service=name, error=str(e))

        logger.warning("Emergency stop completed")

    async def send_command(
        self,
        service_name: str,
        command: PackMLCommand,
        procedure_id: int | None = None,
        source: str = "user",
    ) -> TransitionResult:
        """Send a command to a service via its proxy adapter.

        Args:
            service_name: Name of the service.
            command: PackML command to execute.
            procedure_id: Optional procedure ID for START command.
            source: Origin of command for audit trail.

        Returns:
            TransitionResult indicating success/failure.
        """
        proxy = self._proxies.get(service_name)
        if proxy is None:
            return TransitionResult(
                success=False,
                from_state=PackMLState.UNDEFINED,
                to_state=None,
                error=f"Service '{service_name}' not found",
            )

        from_state = await proxy.get_state()
        defn = self._definitions[service_name]

        # Check interlocks (ABORT/STOP never blocked)
        if command in {PackMLCommand.START, PackMLCommand.UNHOLD} and self._interlock_evaluator:
            interlock = self._check_interlocks(service_name)
            if interlock.interlocked:
                logger.warning(
                    "Command blocked by interlock", service=service_name, command=command.name
                )
                return TransitionResult(
                    success=False,
                    from_state=from_state,
                    to_state=None,
                    error=interlock.reason or "Interlock active",
                )

        # Set procedure ID for START
        if command == PackMLCommand.START:
            if procedure_id is not None:
                self._procedure_ids[service_name] = procedure_id
            else:
                default = next((p for p in defn.procedures if p.is_default), None)
                self._procedure_ids[service_name] = default.id if default else 0

        # Execute via proxy
        result = await proxy.send_command(command, self._procedure_ids[service_name])

        # Audit the command
        audit_result = TransitionResult(
            success=result.success,
            from_state=result.from_state,
            to_state=result.to_state,
            error=result.error,
        )
        await self._audit.log_command(
            service=service_name,
            command=command,
            source=source,
            result=audit_result,
            procedure_id=procedure_id,
        )

        if result.success:
            to_state = result.to_state or await proxy.get_state()
            if to_state != from_state:
                self._notify_subscribers(service_name, from_state, to_state)
                await self._audit.log_state_transition(
                    service=service_name,
                    from_state=from_state,
                    to_state=to_state,
                    trigger=f"{command.name} command",
                )

            if to_state == PackMLState.EXECUTE:
                self._execute_start_times[service_name] = datetime.now(UTC)
                self._start_completion_monitor(service_name)

        return TransitionResult(
            success=result.success,
            from_state=from_state,
            to_state=result.to_state,
            error=result.error,
        )

    def _start_completion_monitor(self, service_name: str) -> None:
        """Start completion monitoring for a service in EXECUTE state."""
        if service_name in self._completion_tasks:
            self._completion_tasks[service_name].cancel()
        task = asyncio.create_task(
            self._completion_loop(service_name), name=f"completion_{service_name}"
        )
        self._completion_tasks[service_name] = task

    async def _state_monitor_loop(self, service_name: str) -> None:
        """Monitor acting states for completion conditions and timeouts."""
        defn = self._definitions[service_name]
        proxy = self._proxies[service_name]
        last_state = await proxy.get_state()
        self._state_entry_times[service_name] = datetime.now(UTC)

        while self._running:
            try:
                state = await proxy.get_state()
                if state != last_state:
                    last_state = state
                    self._state_entry_times[service_name] = datetime.now(UTC)

                # Advance acting states when a condition is met
                for condition in defn.acting_state_conditions:
                    if condition.state == state:
                        tag_value = self._tag_manager.get_value(condition.condition.tag)
                        if tag_value and condition.condition.evaluate(tag_value.value):
                            await self._advance_acting_state(proxy)
                            break

                # Auto-complete acting states if configured and no condition exists
                if defn.timeouts.auto_complete_acting_states and state in self._acting_states():
                    has_condition = any(
                        cond.state == state for cond in defn.acting_state_conditions
                    )
                    if not has_condition:
                        await self._advance_acting_state(proxy)

                # Enforce timeouts for any configured state
                timeout_s = defn.timeouts.timeouts.get(state)
                if timeout_s:
                    entry_time = self._state_entry_times.get(service_name)
                    if entry_time and (datetime.now(UTC) - entry_time).total_seconds() >= timeout_s:
                        await self._handle_timeout(service_name, state, defn.timeouts.on_timeout)

                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(
                    "State monitor error",
                    service=service_name,
                    error=str(e),
                )
                await asyncio.sleep(0.2)

    async def _advance_acting_state(self, proxy: ServiceProxy) -> None:
        """Advance an acting state if the proxy supports it."""
        complete_fn = getattr(proxy, "complete_acting_state", None)
        if callable(complete_fn):
            await complete_fn()

    def _acting_states(self) -> set[PackMLState]:
        """Return the set of acting PackML states."""
        return {
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

    async def _handle_timeout(
        self,
        service_name: str,
        state: PackMLState,
        action: TimeoutAction,
    ) -> None:
        """Handle a timeout according to configured policy."""
        logger.warning(
            "Service state timeout",
            service=service_name,
            state=state.name,
            action=action.value,
        )
        if action == TimeoutAction.ABORT:
            await self.send_command(service_name, PackMLCommand.ABORT, source="timeout_monitor")
        elif action == TimeoutAction.STOP:
            await self.send_command(service_name, PackMLCommand.STOP, source="timeout_monitor")
        elif action == TimeoutAction.HOLD:
            await self.send_command(service_name, PackMLCommand.HOLD, source="timeout_monitor")

    async def _completion_loop(self, service_name: str) -> None:
        """Monitor for service completion via timeout, condition, or self-completing flag."""
        defn = self._definitions[service_name]
        proxy = self._proxies[service_name]
        completion = defn.completion

        try:
            while self._running:
                state = await proxy.get_state()
                if state != PackMLState.EXECUTE:
                    break

                if completion.self_completing:
                    await self.send_command(
                        service_name, PackMLCommand.COMPLETE, source="completion_monitor"
                    )
                    break

                if completion.condition:
                    value = self._tag_manager.get_value(completion.condition.tag)
                    if value and completion.condition.evaluate(value.value):
                        await self.send_command(
                            service_name, PackMLCommand.COMPLETE, source="completion_monitor"
                        )
                        break

                start_time = self._execute_start_times[service_name]
                if completion.timeout_s and start_time:
                    elapsed = (datetime.now(UTC) - start_time).total_seconds()
                    if elapsed >= completion.timeout_s:
                        logger.warning("Service execution timeout", service=service_name)
                        await self.send_command(
                            service_name, PackMLCommand.ABORT, source="completion_monitor"
                        )
                        break

                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass

    async def _plc_sync_loop(self, service_name: str) -> None:
        """Sync state from PLC for thin/hybrid services."""
        defn = self._definitions[service_name]
        proxy = self._proxies[service_name]

        if defn.state_cur_tag is None:
            logger.warning("Thin/hybrid service missing state_cur_tag", service=service_name)
            return

        try:
            last_state = await proxy.get_state()
            while self._running:
                state = await proxy.get_state()
                if state not in (last_state, PackMLState.UNDEFINED):
                    await self._audit.log_state_transition(
                        service=service_name,
                        from_state=last_state,
                        to_state=state,
                        trigger="PLC sync",
                    )
                    self._notify_subscribers(service_name, last_state, state)
                    last_state = state
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass

    def get_service_state(self, name: str) -> PackMLState | None:
        """Get the current state of a service."""
        proxy = self._proxies.get(name)
        if proxy is None:
            return None
        # For sync access, use proxy's state machine if available
        state_machine = getattr(proxy, "state_machine", None)
        if state_machine is not None:
            state: PackMLState = state_machine.current_state
            return state
        return PackMLState.UNDEFINED

    def get_all_service_names(self) -> list[str]:
        """Get a sorted list of configured service names."""
        return sorted(self._definitions.keys())

    def get_service_config(self, name: str) -> ServiceDefinition | None:
        """Get the service definition for a service name."""
        return self._definitions.get(name)

    def is_service_interlocked(self, name: str) -> bool:
        """Return True if the service is currently interlocked."""
        return self._check_interlocks(name).interlocked

    def subscribe(self, callback: StateChangeCallback) -> None:
        """Subscribe to state change notifications."""
        self._subscribers.append(callback)

    def unsubscribe(self, callback: StateChangeCallback) -> None:
        """Unsubscribe from state change notifications."""
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def _notify_subscribers(
        self, service_name: str, from_state: PackMLState, to_state: PackMLState
    ) -> None:
        """Notify subscribers and persist state change."""
        if self._persistence:
            self._track_task(
                asyncio.create_task(
                    self._persist_state(service_name), name=f"persist_{service_name}"
                )
            )

        for callback in self._subscribers:
            try:
                callback(service_name, from_state, to_state)
            except Exception as e:
                logger.warning("Subscriber callback error", service=service_name, error=str(e))

    async def _persist_state(self, service_name: str) -> None:
        """Persist service state to repository."""
        if not self._persistence:
            return
        proxy = self._proxies.get(service_name)
        if proxy is None:
            return

        state = await proxy.get_state()
        try:
            await self._persistence.save_service_state(
                service_name=service_name,
                state=state,
                procedure_id=self._procedure_ids.get(service_name),
                parameters={},
            )
        except Exception as e:
            logger.warning("Failed to persist service state", service=service_name, error=str(e))

    async def recover_services(self) -> None:
        """Restore service states from persistence after restart."""
        if not self._persistence:
            return

        for snapshot in await self._persistence.get_all_service_states():
            proxy = self._proxies.get(snapshot.service_name)
            if not proxy:
                logger.warning("Persisted state for unknown service", service=snapshot.service_name)
                continue

            try:
                restored = PackMLState[snapshot.state]
                state_machine = getattr(proxy, "state_machine", None)
                if state_machine is not None:
                    state_machine._state = restored
                if snapshot.procedure_id is not None:
                    self._procedure_ids[snapshot.service_name] = snapshot.procedure_id
                logger.info(
                    "Service state recovered", service=snapshot.service_name, state=snapshot.state
                )
                await self._persistence.delete_service_state(snapshot.service_name)
            except (KeyError, ValueError) as e:
                logger.warning(
                    "Failed to recover service state", service=snapshot.service_name, error=str(e)
                )

    def _check_interlocks(self, service_name: str) -> InterlockResult:
        """Check interlock conditions for a service."""
        if not self._interlock_evaluator:
            return InterlockResult(interlocked=False)

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

    # Legacy compatibility properties
    @property
    def _services(self) -> dict[str, object]:
        """Legacy access to services for test compatibility."""

        # Return a dict-like object that provides state_machine access
        class ServiceRuntime:
            def __init__(self, proxy: ServiceProxy, defn: ServiceDefinition, proc_id: int | None):
                self.state_machine = getattr(proxy, "state_machine", None)
                self.definition = defn
                self.current_procedure_id = proc_id
                self.quality = Quality.GOOD

        return {
            name: ServiceRuntime(
                self._proxies[name], self._definitions[name], self._procedure_ids[name]
            )
            for name in self._proxies
        }
