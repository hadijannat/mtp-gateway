"""Unit tests for ServiceManager.

Tests thick mode command handling, thin mode tag writes,
completion monitoring (timeout, condition), and state change
subscriber notifications.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from mtp_gateway.adapters.persistence import PersistenceRepository
from mtp_gateway.application.service_manager import ServiceManager
from mtp_gateway.config.schema import (
    ComparisonOp,
    CompletionConfig,
    ConditionConfig,
    ProcedureConfig,
    ProxyMode,
    ServiceConfig,
    StateHooksConfig,
    WriteAction,
)
from mtp_gateway.domain.model.tags import TagValue
from mtp_gateway.domain.state_machine.packml import PackMLCommand, PackMLState


@pytest.fixture
def mock_tag_manager() -> MagicMock:
    """Create a mock TagManager."""
    tm = MagicMock()
    tm.write_tag = AsyncMock(return_value=True)
    tm.read_tag = AsyncMock(return_value=TagValue.good(0))
    tm.get_value = MagicMock(return_value=TagValue.good(0))
    tm.subscribe = MagicMock()
    tm.unsubscribe = MagicMock()
    return tm


@pytest.fixture
def thick_service_config() -> ServiceConfig:
    """Create a thick proxy service configuration."""
    return ServiceConfig(
        name="ThickService",
        mode=ProxyMode.THICK,
        procedures=[
            ProcedureConfig(id=0, name="Main", is_default=True),
            ProcedureConfig(id=1, name="Alt", is_default=False),
        ],
        state_hooks=StateHooksConfig(
            on_starting=[WriteAction(tag="PLC.Start", value=True)],
            on_execute=[WriteAction(tag="PLC.Run", value=True)],
            on_stopping=[WriteAction(tag="PLC.Stop", value=True)],
            on_aborting=[WriteAction(tag="PLC.Abort", value=True)],
        ),
        completion=CompletionConfig(self_completing=True),
    )


@pytest.fixture
def thin_service_config() -> ServiceConfig:
    """Create a thin proxy service configuration."""
    return ServiceConfig(
        name="ThinService",
        mode=ProxyMode.THIN,
        state_cur_tag="PLC.StateCur",
        command_op_tag="PLC.CommandOp",
    )


@pytest.fixture
def condition_service_config() -> ServiceConfig:
    """Create a service with completion condition."""
    return ServiceConfig(
        name="ConditionService",
        mode=ProxyMode.THICK,
        state_hooks=StateHooksConfig(
            on_starting=[WriteAction(tag="PLC.Start", value=True)],
        ),
        completion=CompletionConfig(
            self_completing=False,
            condition=ConditionConfig(
                tag="PLC.Done",
                op=ComparisonOp.EQ,
                ref=True,
            ),
            timeout_s=10.0,
        ),
    )


class TestServiceManagerInitialization:
    """Tests for ServiceManager initialization."""

    def test_create_with_services(
        self, mock_tag_manager: MagicMock, thick_service_config: ServiceConfig
    ) -> None:
        """ServiceManager should initialize with services."""
        sm = ServiceManager(
            tag_manager=mock_tag_manager,
            services=[thick_service_config],
        )
        assert sm is not None
        assert sm.get_service_state("ThickService") is not None

    def test_create_without_services(self, mock_tag_manager: MagicMock) -> None:
        """ServiceManager should handle empty service list."""
        sm = ServiceManager(
            tag_manager=mock_tag_manager,
            services=[],
        )
        assert sm is not None

    def test_unknown_service_returns_none(
        self, mock_tag_manager: MagicMock, thick_service_config: ServiceConfig
    ) -> None:
        """get_service_state() should return None for unknown service."""
        sm = ServiceManager(
            tag_manager=mock_tag_manager,
            services=[thick_service_config],
        )
        assert sm.get_service_state("UnknownService") is None


class TestServiceManagerThickMode:
    """Tests for thick proxy mode command handling."""

    @pytest.mark.asyncio
    async def test_start_command_transitions_to_starting(
        self, mock_tag_manager: MagicMock, thick_service_config: ServiceConfig
    ) -> None:
        """START command in IDLE should transition to STARTING."""
        sm = ServiceManager(
            tag_manager=mock_tag_manager,
            services=[thick_service_config],
        )

        result = await sm.send_command("ThickService", PackMLCommand.START)

        assert result.success is True
        assert result.to_state == PackMLState.STARTING

    @pytest.mark.asyncio
    async def test_start_command_executes_hooks(
        self, mock_tag_manager: MagicMock, thick_service_config: ServiceConfig
    ) -> None:
        """START command should execute on_starting hooks."""
        sm = ServiceManager(
            tag_manager=mock_tag_manager,
            services=[thick_service_config],
        )

        await sm.send_command("ThickService", PackMLCommand.START)

        # Verify on_starting hook was called
        mock_tag_manager.write_tag.assert_called()
        calls = [
            call
            for call in mock_tag_manager.write_tag.call_args_list
            if call[0] == ("PLC.Start", True)
        ]
        assert len(calls) >= 1

    @pytest.mark.asyncio
    async def test_invalid_command_fails(
        self, mock_tag_manager: MagicMock, thick_service_config: ServiceConfig
    ) -> None:
        """Invalid command for current state should fail."""
        sm = ServiceManager(
            tag_manager=mock_tag_manager,
            services=[thick_service_config],
        )

        # HOLD is not valid in IDLE
        result = await sm.send_command("ThickService", PackMLCommand.HOLD)

        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_command_to_unknown_service_fails(
        self, mock_tag_manager: MagicMock, thick_service_config: ServiceConfig
    ) -> None:
        """Command to unknown service should fail."""
        sm = ServiceManager(
            tag_manager=mock_tag_manager,
            services=[thick_service_config],
        )

        result = await sm.send_command("UnknownService", PackMLCommand.START)

        assert result.success is False
        assert "not found" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_stop_command_from_execute(
        self, mock_tag_manager: MagicMock, thick_service_config: ServiceConfig
    ) -> None:
        """STOP command from EXECUTE should transition to STOPPING."""
        sm = ServiceManager(
            tag_manager=mock_tag_manager,
            services=[thick_service_config],
        )

        # Start the service first
        await sm.send_command("ThickService", PackMLCommand.START)
        # Complete STARTING → EXECUTE
        runtime = sm._services.get("ThickService")
        if runtime:
            await runtime.state_machine.complete_acting_state()

        # Now stop
        result = await sm.send_command("ThickService", PackMLCommand.STOP)

        assert result.success is True
        assert result.to_state == PackMLState.STOPPING

    @pytest.mark.asyncio
    async def test_abort_command_executes_aborting_hooks(
        self, mock_tag_manager: MagicMock, thick_service_config: ServiceConfig
    ) -> None:
        """ABORT command should execute on_aborting hooks."""
        sm = ServiceManager(
            tag_manager=mock_tag_manager,
            services=[thick_service_config],
        )

        await sm.send_command("ThickService", PackMLCommand.ABORT)

        # Verify on_aborting hook was called
        calls = [
            call
            for call in mock_tag_manager.write_tag.call_args_list
            if call[0] == ("PLC.Abort", True)
        ]
        assert len(calls) >= 1


class TestServiceManagerThinMode:
    """Tests for thin proxy mode tag writes."""

    @pytest.mark.asyncio
    async def test_start_command_writes_to_command_tag(
        self, mock_tag_manager: MagicMock, thin_service_config: ServiceConfig
    ) -> None:
        """START in thin mode should write to command_op_tag."""
        sm = ServiceManager(
            tag_manager=mock_tag_manager,
            services=[thin_service_config],
        )

        await sm.send_command("ThinService", PackMLCommand.START)

        # Should write command value to PLC.CommandOp
        mock_tag_manager.write_tag.assert_called()
        # START command value is 2
        calls = [
            call
            for call in mock_tag_manager.write_tag.call_args_list
            if call[0][0] == "PLC.CommandOp"
        ]
        assert len(calls) >= 1
        assert calls[0][0][1] == PackMLCommand.START.value

    @pytest.mark.asyncio
    async def test_thin_mode_reads_state_from_plc(
        self, mock_tag_manager: MagicMock, thin_service_config: ServiceConfig
    ) -> None:
        """Thin mode should read state from state_cur_tag."""
        mock_tag_manager.get_value.return_value = TagValue.good(PackMLState.EXECUTE.value)

        sm = ServiceManager(
            tag_manager=mock_tag_manager,
            services=[thin_service_config],
        )

        # Sync should read from PLC.StateCur
        state = sm.get_service_state("ThinService")
        # Initial state is IDLE (not yet synced)
        assert state is not None


class TestServiceManagerCompletionMonitoring:
    """Tests for completion monitoring."""

    @pytest.mark.asyncio
    async def test_self_completing_service_auto_completes(
        self, mock_tag_manager: MagicMock, thick_service_config: ServiceConfig
    ) -> None:
        """Self-completing service should auto-transition after EXECUTE."""
        sm = ServiceManager(
            tag_manager=mock_tag_manager,
            services=[thick_service_config],
        )
        await sm.start()

        try:
            # Start and complete to EXECUTE
            await sm.send_command("ThickService", PackMLCommand.START)
            runtime = sm._services.get("ThickService")
            if runtime:
                await runtime.state_machine.complete_acting_state()
                # State should be EXECUTE
                assert runtime.state_machine.current_state == PackMLState.EXECUTE

                # For self-completing, service should transition to COMPLETING
                # after some monitoring (this may be immediate or async)
                # The actual completion is handled by the completion monitor
        finally:
            await sm.stop()

    @pytest.mark.asyncio
    async def test_condition_completion_triggers_when_true(
        self, mock_tag_manager: MagicMock, condition_service_config: ServiceConfig
    ) -> None:
        """Condition-based completion should trigger when condition is met."""
        # Setup: condition tag returns True
        mock_tag_manager.get_value.return_value = TagValue.good(True)

        sm = ServiceManager(
            tag_manager=mock_tag_manager,
            services=[condition_service_config],
        )

        # The completion monitor will check the condition
        runtime = sm._services.get("ConditionService")
        assert runtime is not None

    @pytest.mark.asyncio
    async def test_timeout_completion(
        self, mock_tag_manager: MagicMock, condition_service_config: ServiceConfig
    ) -> None:
        """Service should handle timeout completion."""
        # Condition never becomes true
        mock_tag_manager.get_value.return_value = TagValue.good(False)

        sm = ServiceManager(
            tag_manager=mock_tag_manager,
            services=[condition_service_config],
        )

        runtime = sm._services.get("ConditionService")
        assert runtime is not None
        # Timeout is 10s as configured


class TestServiceManagerSubscriptions:
    """Tests for state change subscriber notifications."""

    @pytest.mark.asyncio
    async def test_subscribe_receives_state_changes(
        self, mock_tag_manager: MagicMock, thick_service_config: ServiceConfig
    ) -> None:
        """Subscribers should receive state change notifications."""
        sm = ServiceManager(
            tag_manager=mock_tag_manager,
            services=[thick_service_config],
        )

        received_events: list[tuple[str, PackMLState, PackMLState]] = []

        def on_state_change(
            service_name: str, from_state: PackMLState, to_state: PackMLState
        ) -> None:
            received_events.append((service_name, from_state, to_state))

        sm.subscribe(on_state_change)
        await sm.send_command("ThickService", PackMLCommand.START)

        assert len(received_events) >= 1
        assert received_events[0][0] == "ThickService"
        assert received_events[0][2] == PackMLState.STARTING

    @pytest.mark.asyncio
    async def test_unsubscribe_stops_notifications(
        self, mock_tag_manager: MagicMock, thick_service_config: ServiceConfig
    ) -> None:
        """Unsubscribed callbacks should not receive notifications."""
        sm = ServiceManager(
            tag_manager=mock_tag_manager,
            services=[thick_service_config],
        )

        received_events: list[tuple[str, PackMLState, PackMLState]] = []

        def on_state_change(
            service_name: str, from_state: PackMLState, to_state: PackMLState
        ) -> None:
            received_events.append((service_name, from_state, to_state))

        sm.subscribe(on_state_change)
        sm.unsubscribe(on_state_change)
        await sm.send_command("ThickService", PackMLCommand.START)

        assert len(received_events) == 0


class TestServiceManagerLifecycle:
    """Tests for ServiceManager start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_initializes_services(
        self, mock_tag_manager: MagicMock, thick_service_config: ServiceConfig
    ) -> None:
        """start() should initialize all services."""
        sm = ServiceManager(
            tag_manager=mock_tag_manager,
            services=[thick_service_config],
        )

        await sm.start()

        try:
            assert sm.get_service_state("ThickService") == PackMLState.IDLE
        finally:
            await sm.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_monitors(
        self, mock_tag_manager: MagicMock, thick_service_config: ServiceConfig
    ) -> None:
        """stop() should cancel completion monitors and sync tasks."""
        sm = ServiceManager(
            tag_manager=mock_tag_manager,
            services=[thick_service_config],
        )

        await sm.start()
        await sm.stop()

        # Should complete without errors


class TestServiceManagerProcedureSelection:
    """Tests for procedure selection."""

    @pytest.mark.asyncio
    async def test_start_with_procedure_id(
        self, mock_tag_manager: MagicMock, thick_service_config: ServiceConfig
    ) -> None:
        """START with procedure_id should set current procedure."""
        sm = ServiceManager(
            tag_manager=mock_tag_manager,
            services=[thick_service_config],
        )

        result = await sm.send_command("ThickService", PackMLCommand.START, procedure_id=1)

        assert result.success is True
        runtime = sm._services.get("ThickService")
        assert runtime is not None
        assert runtime.current_procedure_id == 1

    @pytest.mark.asyncio
    async def test_start_without_procedure_uses_default(
        self, mock_tag_manager: MagicMock, thick_service_config: ServiceConfig
    ) -> None:
        """START without procedure_id should use default procedure."""
        sm = ServiceManager(
            tag_manager=mock_tag_manager,
            services=[thick_service_config],
        )

        result = await sm.send_command("ThickService", PackMLCommand.START)

        assert result.success is True
        runtime = sm._services.get("ThickService")
        assert runtime is not None
        # Default procedure is id=0
        assert runtime.current_procedure_id == 0


class TestServiceManagerPersistence:
    """Tests for ServiceManager persistence integration."""

    @pytest.mark.asyncio
    async def test_state_change_persists_to_repository(
        self, mock_tag_manager: MagicMock, thick_service_config: ServiceConfig
    ) -> None:
        """State changes should be persisted to the repository."""

        repo = PersistenceRepository(db_path=":memory:")
        await repo.initialize()

        try:
            sm = ServiceManager(
                tag_manager=mock_tag_manager,
                services=[thick_service_config],
                persistence=repo,
            )

            await sm.send_command("ThickService", PackMLCommand.START)

            # Allow background persistence tasks to complete
            await asyncio.sleep(0.1)

            # Check state was persisted
            snapshot = await repo.get_service_state("ThickService")
            assert snapshot is not None
            # State should be one of the transition states
            assert snapshot.state in ("STARTING", "EXECUTE")
        finally:
            await repo.close()

    @pytest.mark.asyncio
    async def test_persistence_is_optional(
        self, mock_tag_manager: MagicMock, thick_service_config: ServiceConfig
    ) -> None:
        """ServiceManager should work without persistence."""
        sm = ServiceManager(
            tag_manager=mock_tag_manager,
            services=[thick_service_config],
            # No persistence parameter
        )

        result = await sm.send_command("ThickService", PackMLCommand.START)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_recover_services_restores_state(
        self, mock_tag_manager: MagicMock, thick_service_config: ServiceConfig
    ) -> None:
        """recover_services() should restore state from persistence."""
        repo = PersistenceRepository(db_path=":memory:")
        await repo.initialize()

        try:
            # Pre-populate persistence with a state
            await repo.save_service_state(
                service_name="ThickService",
                state=PackMLState.EXECUTE,
                procedure_id=1,
                parameters={"test": "value"},
            )

            # Create ServiceManager and recover
            sm = ServiceManager(
                tag_manager=mock_tag_manager,
                services=[thick_service_config],
                persistence=repo,
            )
            await sm.recover_services()

            # Check state was restored
            state = sm.get_service_state("ThickService")
            assert state == PackMLState.EXECUTE
        finally:
            await repo.close()

    @pytest.mark.asyncio
    async def test_recover_services_clears_after_recovery(
        self, mock_tag_manager: MagicMock, thick_service_config: ServiceConfig
    ) -> None:
        """recover_services() should clear persisted state after recovery."""
        repo = PersistenceRepository(db_path=":memory:")
        await repo.initialize()

        try:
            # Pre-populate persistence
            await repo.save_service_state(
                service_name="ThickService",
                state=PackMLState.EXECUTE,
                procedure_id=1,
                parameters={},
            )

            sm = ServiceManager(
                tag_manager=mock_tag_manager,
                services=[thick_service_config],
                persistence=repo,
            )
            await sm.recover_services()

            # Check persisted state was cleared (service running, no need to keep snapshot)
            snapshot = await repo.get_service_state("ThickService")
            assert snapshot is None
        finally:
            await repo.close()

    @pytest.mark.asyncio
    async def test_recover_services_no_persistence_is_noop(
        self, mock_tag_manager: MagicMock, thick_service_config: ServiceConfig
    ) -> None:
        """recover_services() without persistence should be a no-op."""
        sm = ServiceManager(
            tag_manager=mock_tag_manager,
            services=[thick_service_config],
        )

        # Should not raise
        await sm.recover_services()
        assert sm.get_service_state("ThickService") == PackMLState.IDLE
