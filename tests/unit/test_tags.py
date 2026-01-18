"""Unit tests for tag domain models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from mtp_gateway.adapters.persistence import PersistenceRepository
from mtp_gateway.application.tag_manager import TagManager
from mtp_gateway.domain.model.tags import (
    DataType,
    Quality,
    ScaleConfig,
    TagDefinition,
    TagState,
    TagValue,
)


class TestQuality:
    """Tests for Quality enum."""

    def test_is_good(self) -> None:
        assert Quality.GOOD.is_good()
        assert Quality.GOOD_LOCAL_OVERRIDE.is_good()
        assert not Quality.BAD.is_good()
        assert not Quality.UNCERTAIN.is_good()

    def test_is_bad(self) -> None:
        assert Quality.BAD.is_bad()
        assert Quality.BAD_NO_COMMUNICATION.is_bad()
        assert not Quality.GOOD.is_bad()
        assert not Quality.UNCERTAIN.is_bad()

    def test_is_uncertain(self) -> None:
        assert Quality.UNCERTAIN.is_uncertain()
        assert Quality.UNCERTAIN_NO_COMM_LAST_USABLE.is_uncertain()
        assert not Quality.GOOD.is_uncertain()
        assert not Quality.BAD.is_uncertain()

    def test_to_opcua_status_code(self) -> None:
        assert Quality.GOOD.to_opcua_status_code() == 0x00000000
        assert Quality.BAD.to_opcua_status_code() == 0x80000000


class TestDataType:
    """Tests for DataType enum."""

    def test_python_type(self) -> None:
        assert DataType.BOOL.python_type() is bool
        assert DataType.INT16.python_type() is int
        assert DataType.FLOAT32.python_type() is float
        assert DataType.STRING.python_type() is str

    def test_byte_size(self) -> None:
        assert DataType.BOOL.byte_size() == 1
        assert DataType.INT16.byte_size() == 2
        assert DataType.INT32.byte_size() == 4
        assert DataType.FLOAT64.byte_size() == 8
        assert DataType.STRING.byte_size() == 0  # Variable


class TestTagValue:
    """Tests for TagValue immutable value object."""

    def test_create_tag_value(self) -> None:
        now = datetime.now(UTC)
        tv = TagValue(value=42.5, timestamp=now, quality=Quality.GOOD)
        assert tv.value == 42.5
        assert tv.timestamp == now
        assert tv.quality == Quality.GOOD

    def test_tag_value_is_frozen(self) -> None:
        tv = TagValue(value=42.5, timestamp=datetime.now(UTC), quality=Quality.GOOD)
        with pytest.raises(AttributeError):
            tv.value = 100  # type: ignore[misc]

    def test_good_factory(self) -> None:
        tv = TagValue.good(100)
        assert tv.value == 100
        assert tv.quality == Quality.GOOD

    def test_bad_no_comm_factory(self) -> None:
        tv = TagValue.bad_no_comm(last_value=50)
        assert tv.value == 50
        assert tv.quality == Quality.BAD_NO_COMMUNICATION

    def test_uncertain_last_usable_factory(self) -> None:
        original = TagValue.good(75.5)
        uncertain = TagValue.uncertain_last_usable(original)
        assert uncertain.value == 75.5
        assert uncertain.quality == Quality.UNCERTAIN_NO_COMM_LAST_USABLE
        assert uncertain.source_timestamp == original.timestamp


class TestScaleConfig:
    """Tests for ScaleConfig."""

    def test_apply_scale(self) -> None:
        scale = ScaleConfig(gain=0.1, offset=10)
        assert scale.apply(100) == 20.0  # 100 * 0.1 + 10

    def test_reverse_scale(self) -> None:
        scale = ScaleConfig(gain=0.1, offset=10)
        assert scale.reverse(20.0) == 100.0

    def test_reverse_zero_gain_raises(self) -> None:
        scale = ScaleConfig(gain=0, offset=10)
        with pytest.raises(ValueError, match="zero gain"):
            scale.reverse(20.0)


class TestTagDefinition:
    """Tests for TagDefinition."""

    def test_create_definition(self) -> None:
        tag_def = TagDefinition(
            name="temp_sensor",
            connector="plc1",
            address="40001",
            datatype=DataType.FLOAT32,
        )
        assert tag_def.name == "temp_sensor"
        assert tag_def.writable is False

    def test_apply_scale(self) -> None:
        tag_def = TagDefinition(
            name="pressure",
            connector="plc1",
            address="40002",
            datatype=DataType.INT16,
            scale=ScaleConfig(gain=0.01, offset=0),
        )
        assert tag_def.apply_scale(1000) == 10.0

    def test_no_scale_returns_float(self) -> None:
        tag_def = TagDefinition(
            name="raw",
            connector="plc1",
            address="40003",
            datatype=DataType.INT16,
        )
        assert tag_def.apply_scale(100) == 100.0
        assert isinstance(tag_def.apply_scale(100), float)


class TestTagState:
    """Tests for TagState mutable state tracking."""

    def test_initial_state(self) -> None:
        tag_def = TagDefinition(
            name="test",
            connector="plc1",
            address="40001",
            datatype=DataType.FLOAT32,
        )
        state = TagState(definition=tag_def)
        assert state.current_value is None
        assert state.last_good_value is None
        assert state.read_count == 0
        assert state.quality == Quality.BAD_NOT_CONNECTED

    def test_update_with_good_value(self) -> None:
        tag_def = TagDefinition(
            name="test",
            connector="plc1",
            address="40001",
            datatype=DataType.FLOAT32,
        )
        state = TagState(definition=tag_def)

        value = TagValue.good(42.5)
        state.update(value)

        assert state.current_value == value
        assert state.last_good_value == value
        assert state.read_count == 1
        assert state.quality == Quality.GOOD

    def test_update_with_bad_value_preserves_last_good(self) -> None:
        tag_def = TagDefinition(
            name="test",
            connector="plc1",
            address="40001",
            datatype=DataType.FLOAT32,
        )
        state = TagState(definition=tag_def)

        # First update with good value
        good_value = TagValue.good(42.5)
        state.update(good_value)

        # Then update with bad value
        bad_value = TagValue.bad_no_comm(0)
        state.update(bad_value)

        assert state.current_value == bad_value
        assert state.last_good_value == good_value  # Preserved
        assert state.error_count == 1

    def test_subscribe_notifies_on_change(self) -> None:
        tag_def = TagDefinition(
            name="test",
            connector="plc1",
            address="40001",
            datatype=DataType.FLOAT32,
        )
        state = TagState(definition=tag_def)

        notifications: list[tuple[str, TagValue]] = []

        def callback(name: str, value: TagValue) -> None:
            notifications.append((name, value))

        state.subscribe(callback)

        value = TagValue.good(100)
        state.update(value)

        assert len(notifications) == 1
        assert notifications[0] == ("test", value)


class TestTagManagerPersistence:
    """Tests for TagManager persistence integration."""

    @pytest.mark.asyncio
    async def test_tag_manager_accepts_persistence_parameter(self) -> None:
        """TagManager should accept optional persistence parameter."""
        repo = PersistenceRepository(db_path=":memory:")
        await repo.initialize()
        try:
            # Should not raise
            tm = TagManager(
                connectors={},
                tags=[],
                persistence=repo,
            )
            assert tm is not None
        finally:
            await repo.close()

    @pytest.mark.asyncio
    async def test_tag_manager_works_without_persistence(self) -> None:
        """TagManager should work without persistence parameter."""
        # Should not raise
        tm = TagManager(
            connectors={},
            tags=[],
            # No persistence parameter
        )
        assert tm is not None
