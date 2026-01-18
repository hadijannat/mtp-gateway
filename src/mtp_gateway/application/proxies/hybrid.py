"""Hybrid proxy implementation.

In HYBRID mode, the gateway writes commands to the PLC AND
tracks state locally. The PLC state is preferred when available.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from mtp_gateway.application.proxies.base import ProxyResult, ServiceProxy
from mtp_gateway.application.proxies.thin import ThinProxy
from mtp_gateway.domain.state_machine.packml import (
    PackMLCommand,
    PackMLState,
    PackMLStateMachine,
)

if TYPE_CHECKING:
    from mtp_gateway.application.tag_manager import TagManager
    from mtp_gateway.config.schema import ServiceConfig

logger = structlog.get_logger(__name__)


class HybridProxy(ServiceProxy):
    """Hybrid proxy - writes to PLC and tracks locally.

    Combines thin and thick proxy behaviors:
    - Writes commands to PLC (like thin)
    - Tracks state locally (like thick)
    - Prefers PLC state when available

    Responsibilities:
    - Write command values to command_op_tag
    - Maintain local state machine for tracking
    - Return PLC state when available, fall back to local
    """

    def __init__(
        self,
        config: ServiceConfig,
        tag_manager: TagManager,
    ) -> None:
        """Initialize hybrid proxy.

        Args:
            config: Service configuration.
            tag_manager: TagManager for reading/writing tags.
        """
        self._config = config
        self._tag_manager = tag_manager

        # Thin proxy for PLC communication
        self._thin_proxy = ThinProxy(config, tag_manager)

        # Local state machine for tracking
        self._state_machine = PackMLStateMachine(
            name=config.name,
            initial_state=PackMLState.IDLE,
        )

    @property
    def name(self) -> str:
        """Get the service name."""
        return self._config.name

    async def send_command(
        self,
        command: PackMLCommand,
        procedure_id: int | None = None,
    ) -> ProxyResult:
        """Send a command to the PLC and track locally.

        Writes the command to the PLC, then updates the local
        state machine for tracking purposes.

        Args:
            command: PackML command to execute.
            procedure_id: Optional procedure ID.

        Returns:
            ProxyResult indicating write success.
        """
        # Write to PLC first (like thin mode)
        result = await self._thin_proxy.send_command(command, procedure_id)

        if result.success:
            # Also update local state machine for tracking
            await self._state_machine.send_command(command)
            logger.debug(
                "Hybrid proxy: command sent to PLC and tracked locally",
                service=self._config.name,
                command=command.name,
            )

        return result

    async def get_state(self) -> PackMLState:
        """Get current state, preferring PLC state.

        Returns PLC state if available and valid, otherwise
        falls back to local state machine.

        Returns:
            Current PackML state.
        """
        # Try to get state from PLC first
        plc_state = await self._thin_proxy.get_state()

        if plc_state != PackMLState.UNDEFINED:
            # Sync local state with PLC
            if plc_state != self._state_machine.current_state:
                self._state_machine._state = plc_state
            return plc_state

        # Fall back to local state
        return self._state_machine.current_state

    @property
    def state_machine(self) -> PackMLStateMachine:
        """Access the local state machine (for testing/debugging)."""
        return self._state_machine
