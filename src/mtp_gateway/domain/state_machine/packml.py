"""PackML 17-state machine per VDI 2658 / ISA-88.

Implements the standard PackML state machine for MTP service control.
The state machine is thread-safe and supports async callbacks for
state transitions.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Awaitable


class PackMLState(Enum):
    """PackML states per ISA-88 / VDI 2658.

    Integer values match OPC UA NodeId conventions.
    """

    UNDEFINED = 0
    IDLE = 1
    STARTING = 2
    EXECUTE = 3
    COMPLETING = 4
    COMPLETED = 5
    HOLDING = 6
    HELD = 7
    UNHOLDING = 8
    STOPPING = 9
    STOPPED = 10
    ABORTING = 11
    ABORTED = 12
    CLEARING = 13
    SUSPENDING = 14
    SUSPENDED = 15
    UNSUSPENDING = 16
    RESETTING = 17


class PackMLCommand(Enum):
    """PackML commands per ISA-88 / VDI 2658.

    Integer values match OPC UA method input conventions.
    """

    RESET = 1
    START = 2
    STOP = 3
    HOLD = 4
    UNHOLD = 5
    SUSPEND = 6
    UNSUSPEND = 7
    ABORT = 8
    CLEAR = 9
    COMPLETE = 10


@dataclass
class TransitionResult:
    """Result of a state transition attempt.

    Attributes:
        success: Whether the transition was successful
        from_state: The state before the transition attempt
        to_state: The state after transition (None if failed)
        error: Error message if transition failed
    """

    success: bool
    from_state: PackMLState
    to_state: PackMLState | None
    error: str | None = None


# Type alias for async state callbacks
StateCallback = Callable[[PackMLState], Awaitable[None]]


# Valid transitions: (current_state, command) → next_state
# Based on PackML state diagram
_COMMAND_TRANSITIONS: dict[tuple[PackMLState, PackMLCommand], PackMLState] = {
    # From IDLE
    (PackMLState.IDLE, PackMLCommand.START): PackMLState.STARTING,
    (PackMLState.IDLE, PackMLCommand.STOP): PackMLState.STOPPING,
    (PackMLState.IDLE, PackMLCommand.ABORT): PackMLState.ABORTING,
    # From EXECUTE
    (PackMLState.EXECUTE, PackMLCommand.HOLD): PackMLState.HOLDING,
    (PackMLState.EXECUTE, PackMLCommand.SUSPEND): PackMLState.SUSPENDING,
    (PackMLState.EXECUTE, PackMLCommand.STOP): PackMLState.STOPPING,
    (PackMLState.EXECUTE, PackMLCommand.ABORT): PackMLState.ABORTING,
    (PackMLState.EXECUTE, PackMLCommand.COMPLETE): PackMLState.COMPLETING,
    # From HELD
    (PackMLState.HELD, PackMLCommand.UNHOLD): PackMLState.UNHOLDING,
    (PackMLState.HELD, PackMLCommand.STOP): PackMLState.STOPPING,
    (PackMLState.HELD, PackMLCommand.ABORT): PackMLState.ABORTING,
    # From SUSPENDED
    (PackMLState.SUSPENDED, PackMLCommand.UNSUSPEND): PackMLState.UNSUSPENDING,
    (PackMLState.SUSPENDED, PackMLCommand.STOP): PackMLState.STOPPING,
    (PackMLState.SUSPENDED, PackMLCommand.ABORT): PackMLState.ABORTING,
    # From STOPPED
    (PackMLState.STOPPED, PackMLCommand.RESET): PackMLState.RESETTING,
    (PackMLState.STOPPED, PackMLCommand.ABORT): PackMLState.ABORTING,
    # From COMPLETED
    (PackMLState.COMPLETED, PackMLCommand.RESET): PackMLState.RESETTING,
    (PackMLState.COMPLETED, PackMLCommand.STOP): PackMLState.STOPPING,
    (PackMLState.COMPLETED, PackMLCommand.ABORT): PackMLState.ABORTING,
    # From ABORTED
    (PackMLState.ABORTED, PackMLCommand.CLEAR): PackMLState.CLEARING,
    # From acting states (–ING states) - ABORT is typically allowed
    (PackMLState.STARTING, PackMLCommand.ABORT): PackMLState.ABORTING,
    (PackMLState.STARTING, PackMLCommand.STOP): PackMLState.STOPPING,
    (PackMLState.COMPLETING, PackMLCommand.ABORT): PackMLState.ABORTING,
    (PackMLState.COMPLETING, PackMLCommand.STOP): PackMLState.STOPPING,
    (PackMLState.HOLDING, PackMLCommand.ABORT): PackMLState.ABORTING,
    (PackMLState.HOLDING, PackMLCommand.STOP): PackMLState.STOPPING,
    (PackMLState.UNHOLDING, PackMLCommand.ABORT): PackMLState.ABORTING,
    (PackMLState.UNHOLDING, PackMLCommand.STOP): PackMLState.STOPPING,
    (PackMLState.SUSPENDING, PackMLCommand.ABORT): PackMLState.ABORTING,
    (PackMLState.SUSPENDING, PackMLCommand.STOP): PackMLState.STOPPING,
    (PackMLState.UNSUSPENDING, PackMLCommand.ABORT): PackMLState.ABORTING,
    (PackMLState.UNSUSPENDING, PackMLCommand.STOP): PackMLState.STOPPING,
    (PackMLState.STOPPING, PackMLCommand.ABORT): PackMLState.ABORTING,
    (PackMLState.RESETTING, PackMLCommand.ABORT): PackMLState.ABORTING,
    (PackMLState.RESETTING, PackMLCommand.STOP): PackMLState.STOPPING,
    (PackMLState.CLEARING, PackMLCommand.ABORT): PackMLState.ABORTING,
}


# Acting state auto-transitions: acting_state → target_state
_ACTING_STATE_TARGETS: dict[PackMLState, PackMLState] = {
    PackMLState.STARTING: PackMLState.EXECUTE,
    PackMLState.COMPLETING: PackMLState.COMPLETED,
    PackMLState.HOLDING: PackMLState.HELD,
    PackMLState.UNHOLDING: PackMLState.EXECUTE,
    PackMLState.STOPPING: PackMLState.STOPPED,
    PackMLState.ABORTING: PackMLState.ABORTED,
    PackMLState.CLEARING: PackMLState.STOPPED,
    PackMLState.SUSPENDING: PackMLState.SUSPENDED,
    PackMLState.UNSUSPENDING: PackMLState.EXECUTE,
    PackMLState.RESETTING: PackMLState.IDLE,
}


@dataclass
class PackMLStateMachine:
    """Thread-safe PackML state machine with async transition callbacks.

    Implements the 17-state PackML model per VDI 2658 / ISA-88.
    Supports registering callbacks for state entry/exit events.

    Attributes:
        name: Unique identifier for this state machine instance
        current_state: The current PackML state
    """

    name: str
    _state: PackMLState = field(default=PackMLState.IDLE, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _on_enter_callbacks: dict[PackMLState, list[StateCallback]] = field(
        default_factory=dict, repr=False
    )
    _on_exit_callbacks: dict[PackMLState, list[StateCallback]] = field(
        default_factory=dict, repr=False
    )

    def __init__(
        self,
        name: str,
        initial_state: PackMLState = PackMLState.IDLE,
    ) -> None:
        """Initialize the state machine.

        Args:
            name: Unique identifier for this state machine
            initial_state: Starting state (default: IDLE)
        """
        self.name = name
        self._state = initial_state
        self._lock = asyncio.Lock()
        self._on_enter_callbacks = {}
        self._on_exit_callbacks = {}

    @property
    def current_state(self) -> PackMLState:
        """Get the current state."""
        return self._state

    def can_accept_command(self, command: PackMLCommand) -> bool:
        """Check if a command can be accepted in the current state.

        Args:
            command: The command to check

        Returns:
            True if the command is valid for the current state
        """
        return (self._state, command) in _COMMAND_TRANSITIONS

    async def send_command(self, command: PackMLCommand) -> TransitionResult:
        """Send a command to the state machine.

        Thread-safe. Commands are processed atomically with callbacks.

        Args:
            command: The command to execute

        Returns:
            TransitionResult indicating success/failure and state change
        """
        async with self._lock:
            from_state = self._state

            # Check if transition is valid
            key = (from_state, command)
            if key not in _COMMAND_TRANSITIONS:
                return TransitionResult(
                    success=False,
                    from_state=from_state,
                    to_state=None,
                    error=f"Command {command.name} not valid in state {from_state.name}",
                )

            to_state = _COMMAND_TRANSITIONS[key]

            # Execute callbacks in order: exit → update state → enter
            await self._fire_exit_callbacks(from_state)
            self._state = to_state
            await self._fire_enter_callbacks(to_state)

            return TransitionResult(
                success=True,
                from_state=from_state,
                to_state=to_state,
            )

    async def complete_acting_state(self) -> TransitionResult:
        """Complete an acting state (-ING state) to its target state.

        Called after on_<state> hooks have finished executing.
        Only valid for acting states (STARTING, COMPLETING, etc.).

        Returns:
            TransitionResult indicating success/failure and state change
        """
        async with self._lock:
            from_state = self._state

            # Check if current state is an acting state
            if from_state not in _ACTING_STATE_TARGETS:
                return TransitionResult(
                    success=False,
                    from_state=from_state,
                    to_state=None,
                    error=f"State {from_state.name} is not an acting state",
                )

            to_state = _ACTING_STATE_TARGETS[from_state]

            # Execute callbacks in order: exit → update state → enter
            await self._fire_exit_callbacks(from_state)
            self._state = to_state
            await self._fire_enter_callbacks(to_state)

            return TransitionResult(
                success=True,
                from_state=from_state,
                to_state=to_state,
            )

    def on_enter(self, state: PackMLState, callback: StateCallback) -> None:
        """Register a callback for when entering a state.

        Args:
            state: The state to monitor
            callback: Async function to call when entering the state
        """
        if state not in self._on_enter_callbacks:
            self._on_enter_callbacks[state] = []
        self._on_enter_callbacks[state].append(callback)

    def on_exit(self, state: PackMLState, callback: StateCallback) -> None:
        """Register a callback for when exiting a state.

        Args:
            state: The state to monitor
            callback: Async function to call when exiting the state
        """
        if state not in self._on_exit_callbacks:
            self._on_exit_callbacks[state] = []
        self._on_exit_callbacks[state].append(callback)

    async def _fire_enter_callbacks(self, state: PackMLState) -> None:
        """Fire all on_enter callbacks for a state."""
        callbacks = self._on_enter_callbacks.get(state, [])
        for callback in callbacks:
            await callback(state)

    async def _fire_exit_callbacks(self, state: PackMLState) -> None:
        """Fire all on_exit callbacks for a state."""
        callbacks = self._on_exit_callbacks.get(state, [])
        for callback in callbacks:
            await callback(state)
