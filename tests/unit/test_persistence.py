"""Unit tests for Persistence Layer.

Tests for PersistenceRepository with in-memory SQLite database.
Covers service state persistence, tag history, and command audit logging.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from mtp_gateway.adapters.persistence.models import (
    CommandAuditLog,
    ServiceStateSnapshot,
    TagValueRecord,
)
from mtp_gateway.adapters.persistence.repository import PersistenceRepository
from mtp_gateway.domain.model.tags import Quality
from mtp_gateway.domain.state_machine.packml import PackMLState


@pytest.fixture
async def repository() -> PersistenceRepository:
    """Create a PersistenceRepository with in-memory SQLite."""
    repo = PersistenceRepository(db_path=":memory:")
    await repo.initialize()
    return repo


class TestPersistenceRepositoryInitialization:
    """Tests for PersistenceRepository initialization."""

    @pytest.mark.asyncio
    async def test_initialize_creates_tables(self) -> None:
        """initialize() should create all required tables."""
        repo = PersistenceRepository(db_path=":memory:")
        await repo.initialize()
        # Should not raise - tables exist
        await repo.save_service_state(
            service_name="TestService",
            state=PackMLState.IDLE,
            procedure_id=None,
            parameters={},
        )

    @pytest.mark.asyncio
    async def test_initialize_is_idempotent(self) -> None:
        """initialize() should be safe to call multiple times."""
        repo = PersistenceRepository(db_path=":memory:")
        await repo.initialize()
        await repo.initialize()  # Should not raise


class TestServiceStatePersistence:
    """Tests for service state persistence operations."""

    @pytest.mark.asyncio
    async def test_save_and_get_service_state(self, repository: PersistenceRepository) -> None:
        """save_service_state() and get_service_state() round-trip."""
        await repository.save_service_state(
            service_name="Reactor1",
            state=PackMLState.EXECUTE,
            procedure_id=1,
            parameters={"temp": 95.5, "pressure": 2.1},
        )

        snapshot = await repository.get_service_state("Reactor1")

        assert snapshot is not None
        assert snapshot.service_name == "Reactor1"
        assert snapshot.state == PackMLState.EXECUTE.name
        assert snapshot.procedure_id == 1
        assert snapshot.parameters == {"temp": 95.5, "pressure": 2.1}

    @pytest.mark.asyncio
    async def test_service_state_not_found_returns_none(
        self, repository: PersistenceRepository
    ) -> None:
        """get_service_state() returns None for unknown service."""
        snapshot = await repository.get_service_state("UnknownService")
        assert snapshot is None

    @pytest.mark.asyncio
    async def test_save_service_state_updates_existing(
        self, repository: PersistenceRepository
    ) -> None:
        """save_service_state() updates existing record for same service."""
        await repository.save_service_state(
            service_name="Reactor1",
            state=PackMLState.IDLE,
            procedure_id=None,
            parameters={},
        )
        await repository.save_service_state(
            service_name="Reactor1",
            state=PackMLState.EXECUTE,
            procedure_id=2,
            parameters={"flow": 10.0},
        )

        snapshot = await repository.get_service_state("Reactor1")

        assert snapshot is not None
        assert snapshot.state == PackMLState.EXECUTE.name
        assert snapshot.procedure_id == 2
        assert snapshot.parameters == {"flow": 10.0}

    @pytest.mark.asyncio
    async def test_delete_service_state(self, repository: PersistenceRepository) -> None:
        """delete_service_state() removes the service state record."""
        await repository.save_service_state(
            service_name="Reactor1",
            state=PackMLState.EXECUTE,
            procedure_id=1,
            parameters={},
        )

        await repository.delete_service_state("Reactor1")
        snapshot = await repository.get_service_state("Reactor1")

        assert snapshot is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_service_state_is_noop(
        self, repository: PersistenceRepository
    ) -> None:
        """delete_service_state() on unknown service doesn't raise."""
        # Should not raise
        await repository.delete_service_state("NonexistentService")

    @pytest.mark.asyncio
    async def test_get_all_service_states(self, repository: PersistenceRepository) -> None:
        """get_all_service_states() returns all persisted services."""
        await repository.save_service_state(
            service_name="Reactor1",
            state=PackMLState.EXECUTE,
            procedure_id=1,
            parameters={},
        )
        await repository.save_service_state(
            service_name="Mixer1",
            state=PackMLState.IDLE,
            procedure_id=None,
            parameters={},
        )

        states = await repository.get_all_service_states()

        assert len(states) == 2
        names = {s.service_name for s in states}
        assert names == {"Reactor1", "Mixer1"}


class TestTagValueHistory:
    """Tests for tag value history operations."""

    @pytest.mark.asyncio
    async def test_record_tag_value(self, repository: PersistenceRepository) -> None:
        """record_tag_value() stores tag value with timestamp."""
        timestamp = datetime.now(UTC)

        await repository.record_tag_value(
            tag_name="Temperature.PV",
            value=85.5,
            quality=Quality.GOOD,
            timestamp=timestamp,
            source_timestamp=None,
        )

        # Verify by reading back
        history = await repository.get_tag_history(
            tag_name="Temperature.PV",
            start=timestamp - timedelta(seconds=1),
            end=timestamp + timedelta(seconds=1),
        )
        assert len(history) == 1
        assert history[0].tag_name == "Temperature.PV"
        assert history[0].value == 85.5
        assert history[0].quality == Quality.GOOD.name

    @pytest.mark.asyncio
    async def test_record_tag_value_different_types(
        self, repository: PersistenceRepository
    ) -> None:
        """record_tag_value() handles different value types."""
        timestamp = datetime.now(UTC)

        # Integer
        await repository.record_tag_value(
            tag_name="Counter",
            value=42,
            quality=Quality.GOOD,
            timestamp=timestamp,
        )

        # Boolean
        await repository.record_tag_value(
            tag_name="Running",
            value=True,
            quality=Quality.GOOD,
            timestamp=timestamp,
        )

        # String
        await repository.record_tag_value(
            tag_name="Status",
            value="OK",
            quality=Quality.GOOD,
            timestamp=timestamp,
        )

        # Verify all stored correctly
        start = timestamp - timedelta(seconds=1)
        end = timestamp + timedelta(seconds=1)

        counter = await repository.get_tag_history("Counter", start, end)
        assert len(counter) == 1
        assert counter[0].value == 42

        running = await repository.get_tag_history("Running", start, end)
        assert len(running) == 1
        assert running[0].value is True

        status = await repository.get_tag_history("Status", start, end)
        assert len(status) == 1
        assert status[0].value == "OK"

    @pytest.mark.asyncio
    async def test_get_tag_history_in_range(self, repository: PersistenceRepository) -> None:
        """get_tag_history() returns values within time range."""
        base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

        # Record values at different times
        for i in range(5):
            await repository.record_tag_value(
                tag_name="Temp",
                value=20.0 + i,
                quality=Quality.GOOD,
                timestamp=base_time + timedelta(hours=i),
            )

        # Query middle range
        history = await repository.get_tag_history(
            tag_name="Temp",
            start=base_time + timedelta(hours=1),
            end=base_time + timedelta(hours=3),
        )

        # Should include hours 1, 2, 3 (inclusive)
        assert len(history) == 3
        values = [h.value for h in history]
        assert 21.0 in values
        assert 22.0 in values
        assert 23.0 in values

    @pytest.mark.asyncio
    async def test_get_tag_history_empty_range(self, repository: PersistenceRepository) -> None:
        """get_tag_history() returns empty list for no matches."""
        history = await repository.get_tag_history(
            tag_name="NonexistentTag",
            start=datetime.now(UTC) - timedelta(hours=1),
            end=datetime.now(UTC),
        )
        assert history == []

    @pytest.mark.asyncio
    async def test_get_tag_history_orders_by_timestamp(
        self, repository: PersistenceRepository
    ) -> None:
        """get_tag_history() returns values ordered by timestamp ascending."""
        base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

        # Record out of order
        await repository.record_tag_value(
            tag_name="Temp",
            value=30.0,
            quality=Quality.GOOD,
            timestamp=base_time + timedelta(hours=2),
        )
        await repository.record_tag_value(
            tag_name="Temp",
            value=10.0,
            quality=Quality.GOOD,
            timestamp=base_time,
        )
        await repository.record_tag_value(
            tag_name="Temp",
            value=20.0,
            quality=Quality.GOOD,
            timestamp=base_time + timedelta(hours=1),
        )

        history = await repository.get_tag_history(
            tag_name="Temp",
            start=base_time - timedelta(hours=1),
            end=base_time + timedelta(hours=3),
        )

        # Should be sorted by timestamp
        values = [h.value for h in history]
        assert values == [10.0, 20.0, 30.0]

    @pytest.mark.asyncio
    async def test_record_tag_with_source_timestamp(
        self, repository: PersistenceRepository
    ) -> None:
        """record_tag_value() stores source_timestamp when provided."""
        timestamp = datetime.now(UTC)
        source_ts = timestamp - timedelta(milliseconds=50)

        await repository.record_tag_value(
            tag_name="PLCTag",
            value=100,
            quality=Quality.GOOD,
            timestamp=timestamp,
            source_timestamp=source_ts,
        )

        history = await repository.get_tag_history(
            tag_name="PLCTag",
            start=timestamp - timedelta(seconds=1),
            end=timestamp + timedelta(seconds=1),
        )

        assert len(history) == 1
        assert history[0].source_timestamp == source_ts


class TestCommandAuditLog:
    """Tests for command audit logging."""

    @pytest.mark.asyncio
    async def test_log_command(self, repository: PersistenceRepository) -> None:
        """log_command() stores command with all details."""
        timestamp = datetime.now(UTC)

        await repository.log_command(
            timestamp=timestamp,
            command_type="START",
            target="Reactor1",
            parameters={"procedure_id": 1},
            result="SUCCESS",
            error_message=None,
        )

        # Read back
        logs = await repository.get_audit_log(
            start=timestamp - timedelta(seconds=1),
            end=timestamp + timedelta(seconds=1),
        )

        assert len(logs) == 1
        assert logs[0].command_type == "START"
        assert logs[0].target == "Reactor1"
        assert logs[0].parameters == {"procedure_id": 1}
        assert logs[0].result == "SUCCESS"
        assert logs[0].error_message is None

    @pytest.mark.asyncio
    async def test_log_command_with_error(self, repository: PersistenceRepository) -> None:
        """log_command() stores failed commands with error message."""
        timestamp = datetime.now(UTC)

        await repository.log_command(
            timestamp=timestamp,
            command_type="WRITE",
            target="Temperature.SP",
            parameters={"value": 150.0},
            result="FAILED",
            error_message="Value exceeds limit",
        )

        logs = await repository.get_audit_log(
            start=timestamp - timedelta(seconds=1),
            end=timestamp + timedelta(seconds=1),
        )

        assert len(logs) == 1
        assert logs[0].result == "FAILED"
        assert logs[0].error_message == "Value exceeds limit"

    @pytest.mark.asyncio
    async def test_get_audit_log_filtered_by_time(self, repository: PersistenceRepository) -> None:
        """get_audit_log() returns logs within time range."""
        base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

        # Record logs at different times
        for i in range(5):
            await repository.log_command(
                timestamp=base_time + timedelta(hours=i),
                command_type="TEST",
                target=f"Target{i}",
                parameters={},
                result="SUCCESS",
            )

        # Query middle range
        logs = await repository.get_audit_log(
            start=base_time + timedelta(hours=1),
            end=base_time + timedelta(hours=3),
        )

        assert len(logs) == 3
        targets = {log.target for log in logs}
        assert targets == {"Target1", "Target2", "Target3"}

    @pytest.mark.asyncio
    async def test_get_audit_log_empty_returns_empty_list(
        self, repository: PersistenceRepository
    ) -> None:
        """get_audit_log() returns empty list when no logs match."""
        logs = await repository.get_audit_log(
            start=datetime.now(UTC) - timedelta(hours=1),
            end=datetime.now(UTC),
        )
        assert logs == []

    @pytest.mark.asyncio
    async def test_get_audit_log_orders_by_timestamp(
        self, repository: PersistenceRepository
    ) -> None:
        """get_audit_log() returns logs ordered by timestamp ascending."""
        base_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

        # Record out of order
        await repository.log_command(
            timestamp=base_time + timedelta(hours=2),
            command_type="CMD3",
            target="T",
            parameters={},
            result="SUCCESS",
        )
        await repository.log_command(
            timestamp=base_time,
            command_type="CMD1",
            target="T",
            parameters={},
            result="SUCCESS",
        )
        await repository.log_command(
            timestamp=base_time + timedelta(hours=1),
            command_type="CMD2",
            target="T",
            parameters={},
            result="SUCCESS",
        )

        logs = await repository.get_audit_log(
            start=base_time - timedelta(hours=1),
            end=base_time + timedelta(hours=3),
        )

        cmd_types = [log.command_type for log in logs]
        assert cmd_types == ["CMD1", "CMD2", "CMD3"]


class TestServiceStateSnapshotModel:
    """Tests for ServiceStateSnapshot model."""

    def test_model_fields(self) -> None:
        """ServiceStateSnapshot should have expected fields."""
        snapshot = ServiceStateSnapshot(
            service_name="TestService",
            state="EXECUTE",
            procedure_id=1,
            parameters={"key": "value"},
        )

        assert snapshot.service_name == "TestService"
        assert snapshot.state == "EXECUTE"
        assert snapshot.procedure_id == 1
        # Parameters are serialized to JSON internally
        assert snapshot.parameters == '{"key": "value"}'

    def test_parameters_default_empty(self) -> None:
        """parameters should default to None when not provided."""
        snapshot = ServiceStateSnapshot(
            service_name="TestService",
            state="IDLE",
        )
        assert snapshot.parameters is None


class TestTagValueRecordModel:
    """Tests for TagValueRecord model."""

    def test_model_fields(self) -> None:
        """TagValueRecord should have expected fields."""
        timestamp = datetime.now(UTC)
        record = TagValueRecord(
            tag_name="Temp.PV",
            value=85.5,
            quality="GOOD",
            timestamp=timestamp,
            source_timestamp=None,
        )

        assert record.tag_name == "Temp.PV"
        assert record.value == 85.5
        assert record.quality == "GOOD"
        assert record.timestamp == timestamp

    def test_different_value_types(self) -> None:
        """TagValueRecord should handle different value types."""
        timestamp = datetime.now(UTC)

        # Float
        record_float = TagValueRecord(
            tag_name="Float", value=3.14, quality="GOOD", timestamp=timestamp
        )
        assert record_float.value == 3.14

        # Int
        record_int = TagValueRecord(tag_name="Int", value=42, quality="GOOD", timestamp=timestamp)
        assert record_int.value == 42

        # Bool
        record_bool = TagValueRecord(
            tag_name="Bool", value=True, quality="GOOD", timestamp=timestamp
        )
        assert record_bool.value is True


class TestCommandAuditLogModel:
    """Tests for CommandAuditLog model."""

    def test_model_fields(self) -> None:
        """CommandAuditLog should have expected fields."""
        timestamp = datetime.now(UTC)
        log = CommandAuditLog(
            timestamp=timestamp,
            command_type="START",
            target="Reactor1",
            parameters={"proc": 1},
            result="SUCCESS",
            error_message=None,
        )

        assert log.timestamp == timestamp
        assert log.command_type == "START"
        assert log.target == "Reactor1"
        # Parameters are serialized to JSON internally
        assert log.parameters == '{"proc": 1}'
        assert log.result == "SUCCESS"
        assert log.error_message is None
