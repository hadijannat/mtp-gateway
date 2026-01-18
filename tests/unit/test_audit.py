"""Unit tests for AuditTrail.

Tests command logging, state transition logging, and audit retrieval.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from mtp_gateway.application.audit import AuditTrail, CommandAuditEntry, StateTransitionAuditEntry
from mtp_gateway.domain.state_machine.packml import (
    PackMLCommand,
    PackMLState,
    TransitionResult,
)


@pytest.fixture
def audit_trail() -> AuditTrail:
    """Create an AuditTrail instance."""
    return AuditTrail()


class TestAuditEntry:
    """Tests for AuditEntry base class."""

    def test_entry_has_timestamp(self) -> None:
        """AuditEntry should have a timestamp."""
        entry = CommandAuditEntry(
            service="TestService",
            command=PackMLCommand.START,
            source="user",
            result=TransitionResult(
                success=True,
                from_state=PackMLState.IDLE,
                to_state=PackMLState.STARTING,
            ),
        )
        assert entry.timestamp is not None
        assert isinstance(entry.timestamp, datetime)

    def test_entry_has_service_name(self) -> None:
        """AuditEntry should have service name."""
        entry = CommandAuditEntry(
            service="MyService",
            command=PackMLCommand.START,
            source="user",
            result=TransitionResult(
                success=True,
                from_state=PackMLState.IDLE,
                to_state=PackMLState.STARTING,
            ),
        )
        assert entry.service == "MyService"


class TestCommandAuditEntry:
    """Tests for CommandAuditEntry."""

    def test_captures_command(self) -> None:
        """CommandAuditEntry should capture command details."""
        entry = CommandAuditEntry(
            service="TestService",
            command=PackMLCommand.START,
            source="user",
            result=TransitionResult(
                success=True,
                from_state=PackMLState.IDLE,
                to_state=PackMLState.STARTING,
            ),
        )
        assert entry.command == PackMLCommand.START
        assert entry.source == "user"

    def test_captures_result(self) -> None:
        """CommandAuditEntry should capture result."""
        result = TransitionResult(
            success=True,
            from_state=PackMLState.IDLE,
            to_state=PackMLState.STARTING,
        )
        entry = CommandAuditEntry(
            service="TestService",
            command=PackMLCommand.START,
            source="user",
            result=result,
        )
        assert entry.result.success is True
        assert entry.result.from_state == PackMLState.IDLE
        assert entry.result.to_state == PackMLState.STARTING

    def test_captures_failed_command(self) -> None:
        """CommandAuditEntry should capture failed commands."""
        result = TransitionResult(
            success=False,
            from_state=PackMLState.IDLE,
            to_state=None,
            error="Invalid command for state",
        )
        entry = CommandAuditEntry(
            service="TestService",
            command=PackMLCommand.HOLD,
            source="user",
            result=result,
        )
        assert entry.result.success is False
        assert entry.result.error is not None


class TestStateTransitionAuditEntry:
    """Tests for StateTransitionAuditEntry."""

    def test_captures_transition(self) -> None:
        """StateTransitionAuditEntry should capture state transition."""
        entry = StateTransitionAuditEntry(
            service="TestService",
            from_state=PackMLState.IDLE,
            to_state=PackMLState.STARTING,
            trigger="START command",
        )
        assert entry.from_state == PackMLState.IDLE
        assert entry.to_state == PackMLState.STARTING
        assert entry.trigger == "START command"


class TestAuditTrailLogCommand:
    """Tests for AuditTrail.log_command()."""

    @pytest.mark.asyncio
    async def test_logs_successful_command(self, audit_trail: AuditTrail) -> None:
        """log_command() should log successful commands."""
        result = TransitionResult(
            success=True,
            from_state=PackMLState.IDLE,
            to_state=PackMLState.STARTING,
        )
        await audit_trail.log_command(
            service="TestService",
            command=PackMLCommand.START,
            source="user",
            result=result,
        )

        entries = audit_trail.get_entries()
        assert len(entries) == 1
        assert isinstance(entries[0], CommandAuditEntry)
        assert entries[0].command == PackMLCommand.START

    @pytest.mark.asyncio
    async def test_logs_failed_command(self, audit_trail: AuditTrail) -> None:
        """log_command() should log failed commands."""
        result = TransitionResult(
            success=False,
            from_state=PackMLState.IDLE,
            to_state=None,
            error="Command not valid",
        )
        await audit_trail.log_command(
            service="TestService",
            command=PackMLCommand.HOLD,
            source="user",
            result=result,
        )

        entries = audit_trail.get_entries()
        assert len(entries) == 1
        assert entries[0].result.success is False

    @pytest.mark.asyncio
    async def test_logs_with_procedure_id(self, audit_trail: AuditTrail) -> None:
        """log_command() should log procedure ID when provided."""
        result = TransitionResult(
            success=True,
            from_state=PackMLState.IDLE,
            to_state=PackMLState.STARTING,
        )
        await audit_trail.log_command(
            service="TestService",
            command=PackMLCommand.START,
            source="user",
            result=result,
            procedure_id=1,
        )

        entries = audit_trail.get_entries()
        entry = entries[0]
        assert isinstance(entry, CommandAuditEntry)
        assert entry.procedure_id == 1


class TestAuditTrailLogStateTransition:
    """Tests for AuditTrail.log_state_transition()."""

    @pytest.mark.asyncio
    async def test_logs_state_transition(self, audit_trail: AuditTrail) -> None:
        """log_state_transition() should log transitions."""
        await audit_trail.log_state_transition(
            service="TestService",
            from_state=PackMLState.IDLE,
            to_state=PackMLState.STARTING,
            trigger="START command",
        )

        entries = audit_trail.get_entries()
        assert len(entries) == 1
        assert isinstance(entries[0], StateTransitionAuditEntry)
        assert entries[0].from_state == PackMLState.IDLE
        assert entries[0].to_state == PackMLState.STARTING

    @pytest.mark.asyncio
    async def test_logs_transition_trigger(self, audit_trail: AuditTrail) -> None:
        """log_state_transition() should log trigger reason."""
        await audit_trail.log_state_transition(
            service="TestService",
            from_state=PackMLState.STARTING,
            to_state=PackMLState.EXECUTE,
            trigger="Acting state auto-complete",
        )

        entries = audit_trail.get_entries()
        entry = entries[0]
        assert isinstance(entry, StateTransitionAuditEntry)
        assert "auto-complete" in entry.trigger


class TestAuditTrailGetEntries:
    """Tests for AuditTrail.get_entries()."""

    @pytest.mark.asyncio
    async def test_returns_all_entries(self, audit_trail: AuditTrail) -> None:
        """get_entries() should return all entries."""
        result = TransitionResult(
            success=True,
            from_state=PackMLState.IDLE,
            to_state=PackMLState.STARTING,
        )
        await audit_trail.log_command(
            service="Service1",
            command=PackMLCommand.START,
            source="user",
            result=result,
        )
        await audit_trail.log_state_transition(
            service="Service1",
            from_state=PackMLState.IDLE,
            to_state=PackMLState.STARTING,
            trigger="START command",
        )

        entries = audit_trail.get_entries()
        assert len(entries) == 2

    @pytest.mark.asyncio
    async def test_filter_by_service(self, audit_trail: AuditTrail) -> None:
        """get_entries() should filter by service name."""
        result = TransitionResult(
            success=True,
            from_state=PackMLState.IDLE,
            to_state=PackMLState.STARTING,
        )
        await audit_trail.log_command(
            service="Service1",
            command=PackMLCommand.START,
            source="user",
            result=result,
        )
        await audit_trail.log_command(
            service="Service2",
            command=PackMLCommand.START,
            source="user",
            result=result,
        )

        entries = audit_trail.get_entries(service="Service1")
        assert len(entries) == 1
        assert entries[0].service == "Service1"

    @pytest.mark.asyncio
    async def test_entries_ordered_chronologically(self, audit_trail: AuditTrail) -> None:
        """get_entries() should return entries in chronological order."""
        result = TransitionResult(
            success=True,
            from_state=PackMLState.IDLE,
            to_state=PackMLState.STARTING,
        )
        await audit_trail.log_command(
            service="Service1",
            command=PackMLCommand.START,
            source="user",
            result=result,
        )
        await audit_trail.log_command(
            service="Service1",
            command=PackMLCommand.STOP,
            source="user",
            result=result,
        )

        entries = audit_trail.get_entries()
        assert entries[0].timestamp <= entries[1].timestamp


class TestAuditTrailLimits:
    """Tests for AuditTrail entry limits and cleanup."""

    @pytest.mark.asyncio
    async def test_respects_max_entries(self) -> None:
        """AuditTrail should respect max_entries limit."""
        audit_trail = AuditTrail(max_entries=5)

        result = TransitionResult(
            success=True,
            from_state=PackMLState.IDLE,
            to_state=PackMLState.STARTING,
        )
        for i in range(10):
            await audit_trail.log_command(
                service=f"Service{i}",
                command=PackMLCommand.START,
                source="user",
                result=result,
            )

        entries = audit_trail.get_entries()
        assert len(entries) == 5
        # Should keep most recent entries
        assert entries[-1].service == "Service9"

    @pytest.mark.asyncio
    async def test_clear_entries(self, audit_trail: AuditTrail) -> None:
        """clear() should remove all entries."""
        result = TransitionResult(
            success=True,
            from_state=PackMLState.IDLE,
            to_state=PackMLState.STARTING,
        )
        await audit_trail.log_command(
            service="TestService",
            command=PackMLCommand.START,
            source="user",
            result=result,
        )

        audit_trail.clear()
        entries = audit_trail.get_entries()
        assert len(entries) == 0
