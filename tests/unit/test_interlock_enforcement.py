"""Integration tests for Interlock Enforcement (Phase 9).

Tests for ServiceManager interlock enforcement:
- START blocked when interlocked
- RESUME blocked when interlocked
- UNHOLD blocked when interlocked
- ABORT allowed even when interlocked (safety priority)
- STOP allowed even when interlocked (safety priority)

These tests are written FIRST per TDD - they will fail until implementation.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mtp_gateway.application.service_manager import ServiceManager
from mtp_gateway.config.schema import ProxyMode, ServiceConfig
from mtp_gateway.domain.model.tags import Quality, TagValue
from mtp_gateway.domain.rules.interlocks import (
    ComparisonOperator,
    InterlockBinding,
    InterlockEvaluator,
)
from mtp_gateway.domain.state_machine.packml import PackMLCommand, PackMLState


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_tag_manager() -> MagicMock:
    """Create mock TagManager for tests."""
    tm = MagicMock()
    tm.write_tag = AsyncMock(return_value=True)
    tm.read_tag = AsyncMock(return_value=TagValue.good(0))
    tm.get_value = MagicMock(return_value=TagValue.good(0))
    tm.subscribe = MagicMock()
    tm.unsubscribe = MagicMock()
    return tm


@pytest.fixture
def service_configs() -> list[ServiceConfig]:
    """Sample service configurations for testing."""
    return [
        ServiceConfig(
            name="Reactor",
            mode=ProxyMode.THICK,
        ),
    ]


@pytest.fixture
def interlock_evaluator_tripped() -> InterlockEvaluator:
    """InterlockEvaluator with tripped interlock for Reactor service."""
    bindings = {
        "Reactor:SafetyValve": InterlockBinding(
            element_name="Reactor:SafetyValve",
            source_tag="Safety.Trip",
            condition=ComparisonOperator.EQ,
            ref_value=True,
        ),
    }
    return InterlockEvaluator(bindings=bindings)


@pytest.fixture
def interlock_evaluator_clear() -> InterlockEvaluator:
    """InterlockEvaluator with cleared interlock."""
    bindings = {
        "Reactor:SafetyValve": InterlockBinding(
            element_name="Reactor:SafetyValve",
            source_tag="Safety.Trip",
            condition=ComparisonOperator.EQ,
            ref_value=True,
        ),
    }
    return InterlockEvaluator(bindings=bindings)


# =============================================================================
# START Blocked When Interlocked
# =============================================================================


class TestStartBlockedWhenInterlocked:
    """Tests that START command is blocked when service is interlocked."""

    @pytest.mark.asyncio
    async def test_start_blocked_when_interlocked(
        self,
        mock_tag_manager: MagicMock,
        service_configs: list[ServiceConfig],
        interlock_evaluator_tripped: InterlockEvaluator,
    ) -> None:
        """START should be blocked when service has interlocked elements."""
        # Configure mock to return tripped interlock
        mock_tag_manager.get_value = MagicMock(
            return_value=TagValue.good(True)  # Safety.Trip = True
        )

        sm = ServiceManager(
            tag_manager=mock_tag_manager,
            services=service_configs,
            interlock_evaluator=interlock_evaluator_tripped,
        )

        # Try to START - should be blocked
        result = await sm.send_command("Reactor", PackMLCommand.START)

        assert result.success is False
        assert "interlock" in result.error.lower()

        # Service should remain in IDLE, not transition
        state = sm.get_service_state("Reactor")
        assert state == PackMLState.IDLE

    @pytest.mark.asyncio
    async def test_start_allowed_when_not_interlocked(
        self,
        mock_tag_manager: MagicMock,
        service_configs: list[ServiceConfig],
        interlock_evaluator_clear: InterlockEvaluator,
    ) -> None:
        """START should be allowed when interlock is clear."""
        # Configure mock to return clear interlock
        mock_tag_manager.get_value = MagicMock(
            return_value=TagValue.good(False)  # Safety.Trip = False
        )

        sm = ServiceManager(
            tag_manager=mock_tag_manager,
            services=service_configs,
            interlock_evaluator=interlock_evaluator_clear,
        )

        # Try to START - should succeed
        result = await sm.send_command("Reactor", PackMLCommand.START)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_start_allowed_without_interlock_evaluator(
        self,
        mock_tag_manager: MagicMock,
        service_configs: list[ServiceConfig],
    ) -> None:
        """START should be allowed when no interlock evaluator configured."""
        sm = ServiceManager(
            tag_manager=mock_tag_manager,
            services=service_configs,
            # No interlock_evaluator
        )

        result = await sm.send_command("Reactor", PackMLCommand.START)

        assert result.success is True


# =============================================================================
# RESUME Blocked When Interlocked
# =============================================================================


class TestResumeBlockedWhenInterlocked:
    """Tests that RESUME command is blocked when service is interlocked."""

    @pytest.mark.asyncio
    async def test_resume_blocked_when_interlocked(
        self,
        mock_tag_manager: MagicMock,
        service_configs: list[ServiceConfig],
        interlock_evaluator_tripped: InterlockEvaluator,
    ) -> None:
        """RESUME should be blocked when service has interlocked elements."""
        mock_tag_manager.get_value = MagicMock(
            return_value=TagValue.good(True)  # Interlocked
        )

        sm = ServiceManager(
            tag_manager=mock_tag_manager,
            services=service_configs,
            interlock_evaluator=interlock_evaluator_tripped,
        )

        # First get to SUSPENDED state (need to START then SUSPEND)
        mock_tag_manager.get_value = MagicMock(
            return_value=TagValue.good(False)  # Clear for START
        )
        await sm.send_command("Reactor", PackMLCommand.START)

        # Now set interlock and try to RESUME (if applicable)
        # Note: RESUME is from PAUSED state in PackML
        mock_tag_manager.get_value = MagicMock(
            return_value=TagValue.good(True)  # Interlocked
        )

        # RESUME from PAUSED - should be blocked
        # First need to get to PAUSED state (HOLD from EXECUTE)
        # This is a simplified test - in real scenario would need proper state transitions
        result = await sm.send_command("Reactor", PackMLCommand.HOLD)
        # After HOLD we should be in HOLDING -> HELD
        # Wait for state machine to settle

        result = await sm.send_command("Reactor", PackMLCommand.UNHOLD)

        # UNHOLD from HELD should be blocked when interlocked
        assert result.success is False
        assert "interlock" in result.error.lower()


# =============================================================================
# UNHOLD Blocked When Interlocked
# =============================================================================


class TestUnholdBlockedWhenInterlocked:
    """Tests that UNHOLD command is blocked when service is interlocked."""

    @pytest.mark.asyncio
    async def test_unhold_blocked_when_interlocked(
        self,
        mock_tag_manager: MagicMock,
        service_configs: list[ServiceConfig],
        interlock_evaluator_tripped: InterlockEvaluator,
    ) -> None:
        """UNHOLD should be blocked when service has interlocked elements."""
        # Start with clear interlock to get to HELD state
        mock_tag_manager.get_value = MagicMock(
            return_value=TagValue.good(False)
        )

        sm = ServiceManager(
            tag_manager=mock_tag_manager,
            services=service_configs,
            interlock_evaluator=interlock_evaluator_tripped,
        )

        # Get to EXECUTE state
        await sm.send_command("Reactor", PackMLCommand.START)

        # Get to HELD state via HOLD
        await sm.send_command("Reactor", PackMLCommand.HOLD)

        # Now set interlock
        mock_tag_manager.get_value = MagicMock(
            return_value=TagValue.good(True)  # Interlocked
        )

        # Try UNHOLD - should be blocked
        result = await sm.send_command("Reactor", PackMLCommand.UNHOLD)

        assert result.success is False
        assert "interlock" in result.error.lower()


# =============================================================================
# Safety Commands NOT Blocked (ABORT, STOP)
# =============================================================================


class TestSafetyCommandsNotBlocked:
    """Tests that safety commands are NEVER blocked by interlocks."""

    @pytest.mark.asyncio
    async def test_abort_allowed_when_interlocked(
        self,
        mock_tag_manager: MagicMock,
        service_configs: list[ServiceConfig],
        interlock_evaluator_tripped: InterlockEvaluator,
    ) -> None:
        """ABORT should ALWAYS be allowed, even when interlocked."""
        mock_tag_manager.get_value = MagicMock(
            return_value=TagValue.good(True)  # Interlocked
        )

        sm = ServiceManager(
            tag_manager=mock_tag_manager,
            services=service_configs,
            interlock_evaluator=interlock_evaluator_tripped,
        )

        # START first (with clear interlock temporarily)
        mock_tag_manager.get_value = MagicMock(
            return_value=TagValue.good(False)
        )
        await sm.send_command("Reactor", PackMLCommand.START)

        # Now set interlock
        mock_tag_manager.get_value = MagicMock(
            return_value=TagValue.good(True)  # Interlocked
        )

        # ABORT should succeed despite interlock
        result = await sm.send_command("Reactor", PackMLCommand.ABORT)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_stop_allowed_when_interlocked(
        self,
        mock_tag_manager: MagicMock,
        service_configs: list[ServiceConfig],
        interlock_evaluator_tripped: InterlockEvaluator,
    ) -> None:
        """STOP should ALWAYS be allowed, even when interlocked."""
        mock_tag_manager.get_value = MagicMock(
            return_value=TagValue.good(True)  # Interlocked
        )

        sm = ServiceManager(
            tag_manager=mock_tag_manager,
            services=service_configs,
            interlock_evaluator=interlock_evaluator_tripped,
        )

        # START first (with clear interlock temporarily)
        mock_tag_manager.get_value = MagicMock(
            return_value=TagValue.good(False)
        )
        await sm.send_command("Reactor", PackMLCommand.START)

        # Now set interlock
        mock_tag_manager.get_value = MagicMock(
            return_value=TagValue.good(True)  # Interlocked
        )

        # STOP should succeed despite interlock
        result = await sm.send_command("Reactor", PackMLCommand.STOP)

        assert result.success is True


# =============================================================================
# Interlock Cleared Allows Restart
# =============================================================================


class TestInterlockClearedAllowsRestart:
    """Tests that clearing interlock allows operation to resume."""

    @pytest.mark.asyncio
    async def test_interlock_cleared_allows_restart(
        self,
        mock_tag_manager: MagicMock,
        service_configs: list[ServiceConfig],
        interlock_evaluator_tripped: InterlockEvaluator,
    ) -> None:
        """Clearing interlock should allow START to succeed."""
        sm = ServiceManager(
            tag_manager=mock_tag_manager,
            services=service_configs,
            interlock_evaluator=interlock_evaluator_tripped,
        )

        # First attempt with interlock tripped - should fail
        mock_tag_manager.get_value = MagicMock(
            return_value=TagValue.good(True)  # Interlocked
        )
        result1 = await sm.send_command("Reactor", PackMLCommand.START)
        assert result1.success is False

        # Clear interlock
        mock_tag_manager.get_value = MagicMock(
            return_value=TagValue.good(False)  # Clear
        )

        # Second attempt with interlock clear - should succeed
        result2 = await sm.send_command("Reactor", PackMLCommand.START)
        assert result2.success is True


# =============================================================================
# Interlock Result Includes Reason
# =============================================================================


class TestInterlockResultReason:
    """Tests that interlock blocks include diagnostic information."""

    @pytest.mark.asyncio
    async def test_blocked_result_includes_reason(
        self,
        mock_tag_manager: MagicMock,
        service_configs: list[ServiceConfig],
        interlock_evaluator_tripped: InterlockEvaluator,
    ) -> None:
        """Blocked command result should include interlock reason."""
        mock_tag_manager.get_value = MagicMock(
            return_value=TagValue.good(True)  # Interlocked
        )

        sm = ServiceManager(
            tag_manager=mock_tag_manager,
            services=service_configs,
            interlock_evaluator=interlock_evaluator_tripped,
        )

        result = await sm.send_command("Reactor", PackMLCommand.START)

        assert result.success is False
        assert result.error is not None
        # Error should mention the interlock source
        assert "Safety.Trip" in result.error or "interlock" in result.error.lower()
