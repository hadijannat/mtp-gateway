"""Thick proxy implementation.

In THICK mode, the state machine runs entirely in the gateway.
Hooks are executed on state transitions and acting states
auto-complete after hooks finish.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from mtp_gateway.application.proxies.base import ProxyResult, ServiceProxy
from mtp_gateway.domain.model.services import StateHooks
from mtp_gateway.domain.state_machine.packml import (
    PackMLCommand,
    PackMLState,
    PackMLStateMachine,
)

if TYPE_CHECKING:
    from mtp_gateway.application.tag_manager import TagManager
    from mtp_gateway.config.schema import ServiceConfig, WriteAction

logger = structlog.get_logger(__name__)


class ThickProxy(ServiceProxy):
    """Thick proxy - state machine runs in gateway.

    Responsibilities:
    - Manage local PackML state machine
    - Execute state hooks via tag_manager
    - Auto-complete acting states after hooks
    """

    def __init__(
        self,
        config: ServiceConfig,
        tag_manager: TagManager,
    ) -> None:
        """Initialize thick proxy.

        Args:
            config: Service configuration.
            tag_manager: TagManager for writing hooks.
        """
        self._config = config
        self._tag_manager = tag_manager
        self._state_machine = PackMLStateMachine(
            name=config.name,
            initial_state=PackMLState.IDLE,
        )

        # Convert config hooks to domain model
        self._state_hooks = StateHooks.from_config(config.state_hooks)

        # Register state entry callbacks for hooks
        self._register_state_callbacks()

    @property
    def name(self) -> str:
        """Get the service name."""
        return self._config.name

    def _register_state_callbacks(self) -> None:
        """Register callbacks for state transitions to execute hooks."""
        for state in PackMLState:
            hooks = self._state_hooks.get_hooks_for_state(state)
            if hooks:

                async def on_enter_state(
                    entered_state: PackMLState,
                    hooks: tuple[WriteAction, ...] = hooks,
                ) -> None:
                    await self._execute_hooks(hooks)
                    logger.debug(
                        "Executed hooks for state",
                        service=self._config.name,
                        state=entered_state.name,
                        hook_count=len(hooks),
                    )

                self._state_machine.on_enter(state, on_enter_state)

    async def _execute_hooks(self, hooks: tuple[WriteAction, ...]) -> None:
        """Execute a sequence of write actions.

        Args:
            hooks: Tuple of WriteAction to execute.
        """
        for action in hooks:
            await self._tag_manager.write_tag(action.tag, action.value)

    async def send_command(
        self,
        command: PackMLCommand,
        procedure_id: int | None = None,  # noqa: ARG002
    ) -> ProxyResult:
        """Send a command to the thick proxy.

        Executes the command on the local state machine and
        auto-completes acting states after hooks.

        Args:
            command: PackML command to execute.
            procedure_id: Optional procedure ID (stored but not used in thick mode).

        Returns:
            ProxyResult with transition details.
        """
        from_state = self._state_machine.current_state

        result = await self._state_machine.send_command(command)

        # Auto-complete acting states (hooks already executed via callbacks)
        if (
            result.success
            and result.to_state
            and self._is_acting_state(result.to_state)
            and self._should_auto_complete(result.to_state)
        ):
            await self._auto_complete_acting_state()

        return ProxyResult(
            success=result.success,
            from_state=from_state,
            to_state=result.to_state,
            error=result.error,
        )

    async def _auto_complete_acting_state(self) -> None:
        """Auto-complete an acting state after hooks finish."""
        result = await self._state_machine.complete_acting_state()

        # Check if new state is also an acting state
        if result.success and result.to_state and self._is_acting_state(result.to_state):
            await self._auto_complete_acting_state()

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

    def _should_auto_complete(self, state: PackMLState) -> bool:
        """Determine whether acting state should auto-complete."""
        if not self._config.timeouts.auto_complete_acting_states:
            return False
        for condition_state in self._config.acting_state_conditions:
            if PackMLState[condition_state.value] == state:
                return False
        return True

    async def complete_acting_state(self) -> None:
        """Advance from an acting state to its target state."""
        await self._state_machine.complete_acting_state()

    async def get_state(self) -> PackMLState:
        """Get current state from local state machine.

        Returns:
            Current PackML state.
        """
        return self._state_machine.current_state

    @property
    def state_machine(self) -> PackMLStateMachine:
        """Access the underlying state machine (for testing/debugging)."""
        return self._state_machine
