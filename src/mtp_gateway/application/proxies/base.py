"""Base interface for service proxies.

Defines the abstract ServiceProxy interface that THIN, THICK, and HYBRID
proxy implementations must follow.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mtp_gateway.domain.state_machine.packml import PackMLCommand, PackMLState


@dataclass
class ProxyResult:
    """Result of a proxy command execution.

    Attributes:
        success: Whether the command was executed successfully.
        from_state: State before the command.
        to_state: State after the command (None if unknown or failed).
        error: Error message if command failed.
    """

    success: bool
    from_state: PackMLState
    to_state: PackMLState | None = None
    error: str | None = None


class ServiceProxy(ABC):
    """Abstract base class for service proxy adapters.

    Service proxies handle command execution based on the proxy mode:

    | Mode   | State Machine | Command Handling        | State Source   |
    |--------|---------------|-------------------------|----------------|
    | THIN   | In PLC        | Write to command_op_tag | Poll state_cur |
    | THICK  | In Gateway    | Local state machine     | Local SM       |
    | HYBRID | Gateway+PLC   | Write + local tracking  | PLC preferred  |
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Get the service name."""
        ...

    @abstractmethod
    async def send_command(
        self,
        command: PackMLCommand,
        procedure_id: int | None = None,
    ) -> ProxyResult:
        """Send a command to the service.

        Args:
            command: PackML command to execute.
            procedure_id: Optional procedure ID for START command.

        Returns:
            ProxyResult indicating success/failure and state transition.
        """
        ...

    @abstractmethod
    async def get_state(self) -> PackMLState:
        """Get the current state of the service.

        Returns:
            Current PackML state.
        """
        ...
