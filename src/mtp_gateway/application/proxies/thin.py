"""Thin proxy implementation.

In THIN mode, the state machine runs entirely in the PLC.
The gateway writes commands to the PLC and reads state from it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from mtp_gateway.application.proxies.base import ProxyResult, ServiceProxy
from mtp_gateway.domain.state_machine.packml import PackMLCommand, PackMLState

if TYPE_CHECKING:
    from mtp_gateway.application.tag_manager import TagManager
    from mtp_gateway.config.schema import ServiceConfig

logger = structlog.get_logger(__name__)


class ThinProxy(ServiceProxy):
    """Thin proxy - state machine runs in PLC.

    Responsibilities:
    - Write command values to command_op_tag
    - Read state from state_cur_tag
    - No local state machine management
    """

    def __init__(
        self,
        config: ServiceConfig,
        tag_manager: TagManager,
    ) -> None:
        """Initialize thin proxy.

        Args:
            config: Service configuration.
            tag_manager: TagManager for reading/writing tags.
        """
        self._config = config
        self._tag_manager = tag_manager

    @property
    def name(self) -> str:
        """Get the service name."""
        return self._config.name

    async def send_command(
        self,
        command: PackMLCommand,
        procedure_id: int | None = None,  # noqa: ARG002
    ) -> ProxyResult:
        """Send a command to the PLC.

        Writes the command value to the configured command_op_tag.

        Args:
            command: PackML command to execute.
            procedure_id: Optional procedure ID (not used in thin mode).

        Returns:
            ProxyResult indicating write success.
        """
        from_state = await self.get_state()

        if self._config.command_op_tag is None:
            return ProxyResult(
                success=False,
                from_state=from_state,
                to_state=None,
                error="Thin proxy service missing command_op_tag",
            )

        # Write command value to PLC
        success = await self._tag_manager.write_tag(
            self._config.command_op_tag, command.value
        )

        if success:
            logger.debug(
                "Command written to PLC",
                service=self._config.name,
                command=command.name,
                tag=self._config.command_op_tag,
            )
            return ProxyResult(
                success=True,
                from_state=from_state,
                to_state=None,  # Unknown until sync
            )
        else:
            return ProxyResult(
                success=False,
                from_state=from_state,
                to_state=None,
                error="Failed to write command to PLC",
            )

    async def get_state(self) -> PackMLState:
        """Get current state from PLC.

        Reads state from the configured state_cur_tag.

        Returns:
            Current PackML state, or UNDEFINED if unavailable.
        """
        if self._config.state_cur_tag is None:
            return PackMLState.UNDEFINED

        value = self._tag_manager.get_value(self._config.state_cur_tag)
        if value is None or value.value is None:
            return PackMLState.UNDEFINED

        try:
            if isinstance(value.value, int):
                return PackMLState(value.value)
        except ValueError:
            logger.warning(
                "Invalid state value from PLC",
                service=self._config.name,
                value=value.value,
            )

        return PackMLState.UNDEFINED
