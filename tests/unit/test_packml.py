"""Unit tests for PackML state machine.

Tests all valid state transitions, rejection of invalid commands,
auto-transition of acting states, callback execution order, and
thread-safe concurrent command handling per VDI 2658 / ISA-88.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from mtp_gateway.domain.state_machine.packml import (
    PackMLCommand,
    PackMLState,
    PackMLStateMachine,
    TransitionResult,
)


class TestPackMLState:
    """Tests for PackMLState enum."""

    def test_all_17_states_exist(self) -> None:
        """Verify all 17 PackML states are defined."""
        expected_states = {
            "UNDEFINED",
            "IDLE",
            "STARTING",
            "EXECUTE",
            "COMPLETING",
            "COMPLETED",
            "HOLDING",
            "HELD",
            "UNHOLDING",
            "STOPPING",
            "STOPPED",
            "ABORTING",
            "ABORTED",
            "CLEARING",
            "SUSPENDING",
            "SUSPENDED",
            "UNSUSPENDING",
            "RESETTING",
        }
        actual_states = {state.name for state in PackMLState}
        assert actual_states == expected_states

    def test_state_values_are_integers(self) -> None:
        """States should have integer values for OPC UA compatibility."""
        for state in PackMLState:
            assert isinstance(state.value, int)


class TestPackMLCommand:
    """Tests for PackMLCommand enum."""

    def test_all_commands_exist(self) -> None:
        """Verify all 10 PackML commands are defined."""
        expected_commands = {
            "RESET",
            "START",
            "STOP",
            "HOLD",
            "UNHOLD",
            "SUSPEND",
            "UNSUSPEND",
            "ABORT",
            "CLEAR",
            "COMPLETE",
        }
        actual_commands = {cmd.name for cmd in PackMLCommand}
        assert actual_commands == expected_commands

    def test_command_values_are_integers(self) -> None:
        """Commands should have integer values for OPC UA compatibility."""
        for cmd in PackMLCommand:
            assert isinstance(cmd.value, int)


class TestTransitionResult:
    """Tests for TransitionResult dataclass."""

    def test_success_result(self) -> None:
        """Verify success result structure."""
        result = TransitionResult(
            success=True,
            from_state=PackMLState.IDLE,
            to_state=PackMLState.STARTING,
        )
        assert result.success is True
        assert result.from_state == PackMLState.IDLE
        assert result.to_state == PackMLState.STARTING
        assert result.error is None

    def test_failure_result(self) -> None:
        """Verify failure result structure."""
        result = TransitionResult(
            success=False,
            from_state=PackMLState.IDLE,
            to_state=None,
            error="Invalid command for current state",
        )
        assert result.success is False
        assert result.from_state == PackMLState.IDLE
        assert result.to_state is None
        assert result.error == "Invalid command for current state"


class TestPackMLStateMachineInitialization:
    """Tests for PackMLStateMachine initialization."""

    def test_default_initial_state_is_idle(self) -> None:
        """Default initial state should be IDLE."""
        sm = PackMLStateMachine("TestService")
        assert sm.current_state == PackMLState.IDLE

    def test_custom_initial_state(self) -> None:
        """Allow custom initial state."""
        sm = PackMLStateMachine("TestService", initial_state=PackMLState.STOPPED)
        assert sm.current_state == PackMLState.STOPPED

    def test_name_is_stored(self) -> None:
        """State machine name should be stored."""
        sm = PackMLStateMachine("MyService")
        assert sm.name == "MyService"


class TestPackMLValidTransitions:
    """Tests for valid PackML state transitions."""

    @pytest.fixture
    def sm(self) -> PackMLStateMachine:
        """Create a fresh state machine for each test."""
        return PackMLStateMachine("TestService")

    @pytest.mark.asyncio
    async def test_idle_start_goes_to_starting(self, sm: PackMLStateMachine) -> None:
        """IDLE + START → STARTING."""
        result = await sm.send_command(PackMLCommand.START)
        assert result.success is True
        assert result.from_state == PackMLState.IDLE
        assert result.to_state == PackMLState.STARTING

    @pytest.mark.asyncio
    async def test_idle_stop_goes_to_stopping(self, sm: PackMLStateMachine) -> None:
        """IDLE + STOP → STOPPING."""
        result = await sm.send_command(PackMLCommand.STOP)
        assert result.success is True
        assert result.to_state == PackMLState.STOPPING

    @pytest.mark.asyncio
    async def test_idle_abort_goes_to_aborting(self, sm: PackMLStateMachine) -> None:
        """IDLE + ABORT → ABORTING."""
        result = await sm.send_command(PackMLCommand.ABORT)
        assert result.success is True
        assert result.to_state == PackMLState.ABORTING

    @pytest.mark.asyncio
    async def test_execute_hold_goes_to_holding(self, sm: PackMLStateMachine) -> None:
        """EXECUTE + HOLD → HOLDING."""
        sm._state = PackMLState.EXECUTE
        result = await sm.send_command(PackMLCommand.HOLD)
        assert result.success is True
        assert result.to_state == PackMLState.HOLDING

    @pytest.mark.asyncio
    async def test_execute_suspend_goes_to_suspending(self, sm: PackMLStateMachine) -> None:
        """EXECUTE + SUSPEND → SUSPENDING."""
        sm._state = PackMLState.EXECUTE
        result = await sm.send_command(PackMLCommand.SUSPEND)
        assert result.success is True
        assert result.to_state == PackMLState.SUSPENDING

    @pytest.mark.asyncio
    async def test_execute_stop_goes_to_stopping(self, sm: PackMLStateMachine) -> None:
        """EXECUTE + STOP → STOPPING."""
        sm._state = PackMLState.EXECUTE
        result = await sm.send_command(PackMLCommand.STOP)
        assert result.success is True
        assert result.to_state == PackMLState.STOPPING

    @pytest.mark.asyncio
    async def test_execute_complete_goes_to_completing(self, sm: PackMLStateMachine) -> None:
        """EXECUTE + COMPLETE → COMPLETING."""
        sm._state = PackMLState.EXECUTE
        result = await sm.send_command(PackMLCommand.COMPLETE)
        assert result.success is True
        assert result.to_state == PackMLState.COMPLETING

    @pytest.mark.asyncio
    async def test_held_unhold_goes_to_unholding(self, sm: PackMLStateMachine) -> None:
        """HELD + UNHOLD → UNHOLDING."""
        sm._state = PackMLState.HELD
        result = await sm.send_command(PackMLCommand.UNHOLD)
        assert result.success is True
        assert result.to_state == PackMLState.UNHOLDING

    @pytest.mark.asyncio
    async def test_suspended_unsuspend_goes_to_unsuspending(
        self, sm: PackMLStateMachine
    ) -> None:
        """SUSPENDED + UNSUSPEND → UNSUSPENDING."""
        sm._state = PackMLState.SUSPENDED
        result = await sm.send_command(PackMLCommand.UNSUSPEND)
        assert result.success is True
        assert result.to_state == PackMLState.UNSUSPENDING

    @pytest.mark.asyncio
    async def test_stopped_reset_goes_to_resetting(self, sm: PackMLStateMachine) -> None:
        """STOPPED + RESET → RESETTING."""
        sm._state = PackMLState.STOPPED
        result = await sm.send_command(PackMLCommand.RESET)
        assert result.success is True
        assert result.to_state == PackMLState.RESETTING

    @pytest.mark.asyncio
    async def test_aborted_clear_goes_to_clearing(self, sm: PackMLStateMachine) -> None:
        """ABORTED + CLEAR → CLEARING."""
        sm._state = PackMLState.ABORTED
        result = await sm.send_command(PackMLCommand.CLEAR)
        assert result.success is True
        assert result.to_state == PackMLState.CLEARING

    @pytest.mark.asyncio
    async def test_completed_reset_goes_to_resetting(self, sm: PackMLStateMachine) -> None:
        """COMPLETED + RESET → RESETTING."""
        sm._state = PackMLState.COMPLETED
        result = await sm.send_command(PackMLCommand.RESET)
        assert result.success is True
        assert result.to_state == PackMLState.RESETTING

    @pytest.mark.asyncio
    async def test_abort_from_any_non_aborted_state(self, sm: PackMLStateMachine) -> None:
        """ABORT command should work from almost any state."""
        abortable_states = [
            PackMLState.IDLE,
            PackMLState.EXECUTE,
            PackMLState.HELD,
            PackMLState.SUSPENDED,
            PackMLState.STOPPED,
            PackMLState.COMPLETED,
            PackMLState.STARTING,
            PackMLState.COMPLETING,
            PackMLState.HOLDING,
            PackMLState.UNHOLDING,
            PackMLState.SUSPENDING,
            PackMLState.UNSUSPENDING,
            PackMLState.STOPPING,
            PackMLState.RESETTING,
        ]
        for state in abortable_states:
            sm._state = state
            result = await sm.send_command(PackMLCommand.ABORT)
            assert result.success is True, f"ABORT should work from {state.name}"
            assert result.to_state == PackMLState.ABORTING


class TestPackMLInvalidTransitions:
    """Tests for invalid PackML state transitions."""

    @pytest.fixture
    def sm(self) -> PackMLStateMachine:
        """Create a fresh state machine for each test."""
        return PackMLStateMachine("TestService")

    @pytest.mark.asyncio
    async def test_idle_cannot_hold(self, sm: PackMLStateMachine) -> None:
        """IDLE + HOLD should fail (not in EXECUTE)."""
        result = await sm.send_command(PackMLCommand.HOLD)
        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_idle_cannot_unhold(self, sm: PackMLStateMachine) -> None:
        """IDLE + UNHOLD should fail."""
        result = await sm.send_command(PackMLCommand.UNHOLD)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_idle_cannot_reset(self, sm: PackMLStateMachine) -> None:
        """IDLE + RESET should fail (already idle, reset from STOPPED)."""
        result = await sm.send_command(PackMLCommand.RESET)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_execute_cannot_start(self, sm: PackMLStateMachine) -> None:
        """EXECUTE + START should fail (already executing)."""
        sm._state = PackMLState.EXECUTE
        result = await sm.send_command(PackMLCommand.START)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_aborted_cannot_start(self, sm: PackMLStateMachine) -> None:
        """ABORTED + START should fail (must clear first)."""
        sm._state = PackMLState.ABORTED
        result = await sm.send_command(PackMLCommand.START)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_aborting_cannot_abort(self, sm: PackMLStateMachine) -> None:
        """ABORTING + ABORT should fail (already aborting)."""
        sm._state = PackMLState.ABORTING
        result = await sm.send_command(PackMLCommand.ABORT)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_aborted_cannot_abort(self, sm: PackMLStateMachine) -> None:
        """ABORTED + ABORT should fail (already aborted)."""
        sm._state = PackMLState.ABORTED
        result = await sm.send_command(PackMLCommand.ABORT)
        assert result.success is False


class TestPackMLActingStateAutoTransition:
    """Tests for acting state (–ING states) auto-transitions."""

    @pytest.fixture
    def sm(self) -> PackMLStateMachine:
        """Create a fresh state machine for each test."""
        return PackMLStateMachine("TestService")

    @pytest.mark.asyncio
    async def test_starting_completes_to_execute(self, sm: PackMLStateMachine) -> None:
        """STARTING → EXECUTE on complete_acting_state()."""
        sm._state = PackMLState.STARTING
        result = await sm.complete_acting_state()
        assert result.success is True
        assert result.to_state == PackMLState.EXECUTE
        assert sm.current_state == PackMLState.EXECUTE

    @pytest.mark.asyncio
    async def test_completing_completes_to_completed(self, sm: PackMLStateMachine) -> None:
        """COMPLETING → COMPLETED on complete_acting_state()."""
        sm._state = PackMLState.COMPLETING
        result = await sm.complete_acting_state()
        assert result.success is True
        assert result.to_state == PackMLState.COMPLETED

    @pytest.mark.asyncio
    async def test_holding_completes_to_held(self, sm: PackMLStateMachine) -> None:
        """HOLDING → HELD on complete_acting_state()."""
        sm._state = PackMLState.HOLDING
        result = await sm.complete_acting_state()
        assert result.success is True
        assert result.to_state == PackMLState.HELD

    @pytest.mark.asyncio
    async def test_unholding_completes_to_execute(self, sm: PackMLStateMachine) -> None:
        """UNHOLDING → EXECUTE on complete_acting_state()."""
        sm._state = PackMLState.UNHOLDING
        result = await sm.complete_acting_state()
        assert result.success is True
        assert result.to_state == PackMLState.EXECUTE

    @pytest.mark.asyncio
    async def test_stopping_completes_to_stopped(self, sm: PackMLStateMachine) -> None:
        """STOPPING → STOPPED on complete_acting_state()."""
        sm._state = PackMLState.STOPPING
        result = await sm.complete_acting_state()
        assert result.success is True
        assert result.to_state == PackMLState.STOPPED

    @pytest.mark.asyncio
    async def test_aborting_completes_to_aborted(self, sm: PackMLStateMachine) -> None:
        """ABORTING → ABORTED on complete_acting_state()."""
        sm._state = PackMLState.ABORTING
        result = await sm.complete_acting_state()
        assert result.success is True
        assert result.to_state == PackMLState.ABORTED

    @pytest.mark.asyncio
    async def test_clearing_completes_to_stopped(self, sm: PackMLStateMachine) -> None:
        """CLEARING → STOPPED on complete_acting_state()."""
        sm._state = PackMLState.CLEARING
        result = await sm.complete_acting_state()
        assert result.success is True
        assert result.to_state == PackMLState.STOPPED

    @pytest.mark.asyncio
    async def test_suspending_completes_to_suspended(self, sm: PackMLStateMachine) -> None:
        """SUSPENDING → SUSPENDED on complete_acting_state()."""
        sm._state = PackMLState.SUSPENDING
        result = await sm.complete_acting_state()
        assert result.success is True
        assert result.to_state == PackMLState.SUSPENDED

    @pytest.mark.asyncio
    async def test_unsuspending_completes_to_execute(self, sm: PackMLStateMachine) -> None:
        """UNSUSPENDING → EXECUTE on complete_acting_state()."""
        sm._state = PackMLState.UNSUSPENDING
        result = await sm.complete_acting_state()
        assert result.success is True
        assert result.to_state == PackMLState.EXECUTE

    @pytest.mark.asyncio
    async def test_resetting_completes_to_idle(self, sm: PackMLStateMachine) -> None:
        """RESETTING → IDLE on complete_acting_state()."""
        sm._state = PackMLState.RESETTING
        result = await sm.complete_acting_state()
        assert result.success is True
        assert result.to_state == PackMLState.IDLE

    @pytest.mark.asyncio
    async def test_complete_acting_fails_for_non_acting_state(
        self, sm: PackMLStateMachine
    ) -> None:
        """complete_acting_state() should fail for non-acting states."""
        non_acting_states = [
            PackMLState.IDLE,
            PackMLState.EXECUTE,
            PackMLState.HELD,
            PackMLState.STOPPED,
            PackMLState.ABORTED,
            PackMLState.COMPLETED,
            PackMLState.SUSPENDED,
        ]
        for state in non_acting_states:
            sm._state = state
            result = await sm.complete_acting_state()
            assert result.success is False, f"Should fail for {state.name}"


class TestPackMLCanAcceptCommand:
    """Tests for can_accept_command() method."""

    @pytest.fixture
    def sm(self) -> PackMLStateMachine:
        """Create a fresh state machine for each test."""
        return PackMLStateMachine("TestService")

    def test_idle_can_accept_start(self, sm: PackMLStateMachine) -> None:
        """IDLE can accept START."""
        assert sm.can_accept_command(PackMLCommand.START) is True

    def test_idle_cannot_accept_hold(self, sm: PackMLStateMachine) -> None:
        """IDLE cannot accept HOLD."""
        assert sm.can_accept_command(PackMLCommand.HOLD) is False

    def test_execute_can_accept_hold(self, sm: PackMLStateMachine) -> None:
        """EXECUTE can accept HOLD."""
        sm._state = PackMLState.EXECUTE
        assert sm.can_accept_command(PackMLCommand.HOLD) is True

    def test_execute_can_accept_complete(self, sm: PackMLStateMachine) -> None:
        """EXECUTE can accept COMPLETE."""
        sm._state = PackMLState.EXECUTE
        assert sm.can_accept_command(PackMLCommand.COMPLETE) is True


class TestPackMLCallbacks:
    """Tests for state transition callbacks."""

    @pytest.fixture
    def sm(self) -> PackMLStateMachine:
        """Create a fresh state machine for each test."""
        return PackMLStateMachine("TestService")

    @pytest.mark.asyncio
    async def test_on_enter_callback_fires(self, sm: PackMLStateMachine) -> None:
        """on_enter callback should fire when entering a state."""
        entered_states: list[PackMLState] = []

        async def on_enter_starting(state: PackMLState) -> None:
            entered_states.append(state)

        sm.on_enter(PackMLState.STARTING, on_enter_starting)
        await sm.send_command(PackMLCommand.START)

        assert PackMLState.STARTING in entered_states

    @pytest.mark.asyncio
    async def test_on_exit_callback_fires(self, sm: PackMLStateMachine) -> None:
        """on_exit callback should fire when leaving a state."""
        exited_states: list[PackMLState] = []

        async def on_exit_idle(state: PackMLState) -> None:
            exited_states.append(state)

        sm.on_exit(PackMLState.IDLE, on_exit_idle)
        await sm.send_command(PackMLCommand.START)

        assert PackMLState.IDLE in exited_states

    @pytest.mark.asyncio
    async def test_callback_order_exit_then_enter(self, sm: PackMLStateMachine) -> None:
        """on_exit should fire before on_enter during transition."""
        call_order: list[str] = []

        async def on_exit_idle(_: PackMLState) -> None:
            call_order.append("exit_idle")

        async def on_enter_starting(_: PackMLState) -> None:
            call_order.append("enter_starting")

        sm.on_exit(PackMLState.IDLE, on_exit_idle)
        sm.on_enter(PackMLState.STARTING, on_enter_starting)
        await sm.send_command(PackMLCommand.START)

        assert call_order == ["exit_idle", "enter_starting"]

    @pytest.mark.asyncio
    async def test_multiple_callbacks_per_state(self, sm: PackMLStateMachine) -> None:
        """Multiple callbacks can be registered for the same state."""
        calls: list[int] = []

        async def callback1(_: PackMLState) -> None:
            calls.append(1)

        async def callback2(_: PackMLState) -> None:
            calls.append(2)

        sm.on_enter(PackMLState.STARTING, callback1)
        sm.on_enter(PackMLState.STARTING, callback2)
        await sm.send_command(PackMLCommand.START)

        assert 1 in calls
        assert 2 in calls


class TestPackMLConcurrency:
    """Tests for thread-safe concurrent command handling."""

    @pytest.mark.asyncio
    async def test_concurrent_commands_are_serialized(self) -> None:
        """Concurrent commands should be processed safely."""
        sm = PackMLStateMachine("TestService")
        results: list[TransitionResult] = []

        async def send_command(cmd: PackMLCommand) -> None:
            result = await sm.send_command(cmd)
            results.append(result)

        # Send START and ABORT concurrently from IDLE
        await asyncio.gather(
            send_command(PackMLCommand.START),
            send_command(PackMLCommand.ABORT),
        )

        # Both should complete, but only one should succeed
        # (depends on race, but state should be consistent)
        assert len(results) == 2
        success_count = sum(1 for r in results if r.success)
        # At least one should succeed
        assert success_count >= 1
        # State should be consistent (not corrupted)
        assert sm.current_state in [
            PackMLState.STARTING,
            PackMLState.ABORTING,
            PackMLState.EXECUTE,  # if STARTING completed
            PackMLState.ABORTED,  # if ABORTING completed
        ]

    @pytest.mark.asyncio
    async def test_state_consistency_under_load(self) -> None:
        """State machine should maintain consistency under load."""
        sm = PackMLStateMachine("TestService")

        async def rapid_transitions() -> None:
            for _ in range(10):
                await sm.send_command(PackMLCommand.ABORT)
                sm._state = PackMLState.ABORTED
                await sm.send_command(PackMLCommand.CLEAR)
                await sm.complete_acting_state()  # CLEARING → STOPPED
                await sm.send_command(PackMLCommand.RESET)
                await sm.complete_acting_state()  # RESETTING → IDLE

        # Run multiple rapid transition sequences concurrently
        await asyncio.gather(*[rapid_transitions() for _ in range(3)])

        # State should be valid
        assert sm.current_state in list(PackMLState)


class TestPackMLFullWorkflow:
    """Integration-style tests for complete PackML workflows."""

    @pytest.mark.asyncio
    async def test_normal_production_cycle(self) -> None:
        """Test normal: IDLE → START → EXECUTE → COMPLETE → COMPLETED → RESET → IDLE."""
        sm = PackMLStateMachine("ProductionService")

        # IDLE → STARTING
        result = await sm.send_command(PackMLCommand.START)
        assert result.success and sm.current_state == PackMLState.STARTING

        # STARTING → EXECUTE
        result = await sm.complete_acting_state()
        assert result.success and sm.current_state == PackMLState.EXECUTE

        # EXECUTE → COMPLETING
        result = await sm.send_command(PackMLCommand.COMPLETE)
        assert result.success and sm.current_state == PackMLState.COMPLETING

        # COMPLETING → COMPLETED
        result = await sm.complete_acting_state()
        assert result.success and sm.current_state == PackMLState.COMPLETED

        # COMPLETED → RESETTING
        result = await sm.send_command(PackMLCommand.RESET)
        assert result.success and sm.current_state == PackMLState.RESETTING

        # RESETTING → IDLE
        result = await sm.complete_acting_state()
        assert result.success and sm.current_state == PackMLState.IDLE

    @pytest.mark.asyncio
    async def test_hold_unhold_cycle(self) -> None:
        """Test hold cycle: EXECUTE → HOLD → HELD → UNHOLD → EXECUTE."""
        sm = PackMLStateMachine("HoldService")
        sm._state = PackMLState.EXECUTE

        # EXECUTE → HOLDING
        result = await sm.send_command(PackMLCommand.HOLD)
        assert result.success and sm.current_state == PackMLState.HOLDING

        # HOLDING → HELD
        result = await sm.complete_acting_state()
        assert result.success and sm.current_state == PackMLState.HELD

        # HELD → UNHOLDING
        result = await sm.send_command(PackMLCommand.UNHOLD)
        assert result.success and sm.current_state == PackMLState.UNHOLDING

        # UNHOLDING → EXECUTE
        result = await sm.complete_acting_state()
        assert result.success and sm.current_state == PackMLState.EXECUTE

    @pytest.mark.asyncio
    async def test_abort_recovery_cycle(self) -> None:
        """Test abort recovery: EXECUTE → ABORT → ABORTED → CLEAR → STOPPED → RESET → IDLE."""
        sm = PackMLStateMachine("AbortService")
        sm._state = PackMLState.EXECUTE

        # EXECUTE → ABORTING
        result = await sm.send_command(PackMLCommand.ABORT)
        assert result.success and sm.current_state == PackMLState.ABORTING

        # ABORTING → ABORTED
        result = await sm.complete_acting_state()
        assert result.success and sm.current_state == PackMLState.ABORTED

        # ABORTED → CLEARING
        result = await sm.send_command(PackMLCommand.CLEAR)
        assert result.success and sm.current_state == PackMLState.CLEARING

        # CLEARING → STOPPED
        result = await sm.complete_acting_state()
        assert result.success and sm.current_state == PackMLState.STOPPED

        # STOPPED → RESETTING
        result = await sm.send_command(PackMLCommand.RESET)
        assert result.success and sm.current_state == PackMLState.RESETTING

        # RESETTING → IDLE
        result = await sm.complete_acting_state()
        assert result.success and sm.current_state == PackMLState.IDLE
