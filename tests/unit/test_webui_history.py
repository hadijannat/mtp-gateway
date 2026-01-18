"""Tests for WebUI history recording and querying.

Tests for:
- HistoryRecorder service (buffering and flushing)
- HistoryRepository database operations
- History aggregation functions
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from mtp_gateway.adapters.northbound.webui.services.history_recorder import (
    HistoryConfig,
    HistoryRecorder,
)


class TestHistoryConfig:
    """Tests for HistoryConfig dataclass."""

    def test_default_values(self) -> None:
        """Should have sensible default values."""
        config = HistoryConfig()

        assert config.flush_interval == 1.0
        assert config.max_buffer_size == 100
        assert config.exclude_tags is None
        assert config.include_tags is None

    def test_custom_values(self) -> None:
        """Should accept custom values."""
        config = HistoryConfig(
            flush_interval=5.0,
            max_buffer_size=500,
            exclude_tags={"diagnostic_1", "diagnostic_2"},
            include_tags={"temp_1", "temp_2"},
        )

        assert config.flush_interval == 5.0
        assert config.max_buffer_size == 500
        assert config.exclude_tags == {"diagnostic_1", "diagnostic_2"}
        assert config.include_tags == {"temp_1", "temp_2"}


class TestHistoryRecorder:
    """Tests for HistoryRecorder service."""

    @pytest.fixture
    def mock_tag_manager(self) -> MagicMock:
        """Create a mock TagManager."""
        tag_manager = MagicMock()
        tag_manager.subscribe = MagicMock()
        tag_manager.unsubscribe = MagicMock()
        return tag_manager

    @pytest.fixture
    def mock_db_pool(self) -> MagicMock:
        """Create a mock DatabasePool."""
        db_pool = MagicMock()
        db_pool.is_connected = True
        db_pool.pool = MagicMock()
        return db_pool

    @pytest.fixture
    def recorder(self, mock_tag_manager: MagicMock) -> HistoryRecorder:
        """Create a HistoryRecorder without database."""
        return HistoryRecorder(
            tag_manager=mock_tag_manager,
            db_pool=None,
            config=HistoryConfig(flush_interval=0.1, max_buffer_size=10),
        )

    def test_init_default_config(self, mock_tag_manager: MagicMock) -> None:
        """Should use default config if none provided."""
        recorder = HistoryRecorder(tag_manager=mock_tag_manager)

        assert recorder._config.flush_interval == 1.0
        assert recorder._config.max_buffer_size == 100
        assert not recorder._running

    def test_init_custom_config(self, mock_tag_manager: MagicMock) -> None:
        """Should use provided config."""
        config = HistoryConfig(flush_interval=5.0, max_buffer_size=200)
        recorder = HistoryRecorder(tag_manager=mock_tag_manager, config=config)

        assert recorder._config.flush_interval == 5.0
        assert recorder._config.max_buffer_size == 200

    @pytest.mark.asyncio
    async def test_start_subscribes_to_tag_manager(
        self,
        recorder: HistoryRecorder,
        mock_tag_manager: MagicMock,
    ) -> None:
        """Should subscribe to tag changes on start."""
        await recorder.start()
        try:
            mock_tag_manager.subscribe.assert_called_once_with(recorder._on_tag_change)
            assert recorder.is_running
        finally:
            await recorder.stop()

    @pytest.mark.asyncio
    async def test_start_is_idempotent(
        self,
        recorder: HistoryRecorder,
        mock_tag_manager: MagicMock,
    ) -> None:
        """Should not subscribe twice if already running."""
        await recorder.start()
        try:
            await recorder.start()  # Second call should be no-op

            # Should only subscribe once
            assert mock_tag_manager.subscribe.call_count == 1
        finally:
            await recorder.stop()

    @pytest.mark.asyncio
    async def test_stop_unsubscribes_from_tag_manager(
        self,
        recorder: HistoryRecorder,
        mock_tag_manager: MagicMock,
    ) -> None:
        """Should unsubscribe from tag changes on stop."""
        await recorder.start()
        await recorder.stop()

        mock_tag_manager.unsubscribe.assert_called_once_with(recorder._on_tag_change)
        assert not recorder.is_running

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(
        self,
        recorder: HistoryRecorder,
        mock_tag_manager: MagicMock,
    ) -> None:
        """Should handle multiple stop calls gracefully."""
        await recorder.start()
        await recorder.stop()
        await recorder.stop()  # Second call should be no-op

        # Should only unsubscribe once
        assert mock_tag_manager.unsubscribe.call_count == 1

    def test_on_tag_change_buffers_record(self, recorder: HistoryRecorder) -> None:
        """Should buffer tag value changes."""
        mock_value = MagicMock()
        mock_value.value = 25.5
        mock_value.quality = MagicMock(name="good")

        recorder._on_tag_change("temp_1", mock_value)

        assert recorder.buffer_size == 1

    def test_on_tag_change_respects_include_filter(self, mock_tag_manager: MagicMock) -> None:
        """Should only record tags in include list."""
        config = HistoryConfig(include_tags={"allowed_tag"})
        recorder = HistoryRecorder(tag_manager=mock_tag_manager, config=config)

        mock_value = MagicMock()
        mock_value.value = 10.0
        mock_value.quality = MagicMock(name="good")

        # Allowed tag should be recorded
        recorder._on_tag_change("allowed_tag", mock_value)
        assert recorder.buffer_size == 1

        # Other tag should be ignored
        recorder._on_tag_change("other_tag", mock_value)
        assert recorder.buffer_size == 1

    def test_on_tag_change_respects_exclude_filter(self, mock_tag_manager: MagicMock) -> None:
        """Should skip tags in exclude list."""
        config = HistoryConfig(exclude_tags={"excluded_tag"})
        recorder = HistoryRecorder(tag_manager=mock_tag_manager, config=config)

        mock_value = MagicMock()
        mock_value.value = 10.0
        mock_value.quality = MagicMock(name="good")

        # Excluded tag should be ignored
        recorder._on_tag_change("excluded_tag", mock_value)
        assert recorder.buffer_size == 0

        # Other tag should be recorded
        recorder._on_tag_change("other_tag", mock_value)
        assert recorder.buffer_size == 1

    def test_on_tag_change_handles_none_value(self, recorder: HistoryRecorder) -> None:
        """Should handle None values gracefully."""
        mock_value = MagicMock()
        mock_value.value = None
        mock_value.quality = MagicMock(name="bad")

        recorder._on_tag_change("temp_1", mock_value)

        assert recorder.buffer_size == 1

    @pytest.mark.asyncio
    async def test_record_value_adds_to_buffer(self, recorder: HistoryRecorder) -> None:
        """Should allow manual value recording."""
        await recorder.record_value("manual_tag", 42.0, quality="good")

        assert recorder.buffer_size == 1

    @pytest.mark.asyncio
    async def test_record_value_with_timestamp(self, recorder: HistoryRecorder) -> None:
        """Should accept custom timestamp."""
        timestamp = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
        await recorder.record_value("manual_tag", 42.0, timestamp=timestamp)

        assert recorder.buffer_size == 1
        # Check the buffered record has our timestamp
        record = recorder._buffer[0]
        assert record[0] == timestamp

    def test_properties_return_correct_values(self, recorder: HistoryRecorder) -> None:
        """Should expose statistics via properties."""
        assert recorder.is_running is False
        assert recorder.buffer_size == 0
        assert recorder.records_written == 0
        assert recorder.flush_count == 0


class TestHistoryRecorderFlush:
    """Tests for HistoryRecorder flush behavior."""

    @pytest.fixture
    def mock_tag_manager(self) -> MagicMock:
        """Create a mock TagManager."""
        tag_manager = MagicMock()
        tag_manager.subscribe = MagicMock()
        tag_manager.unsubscribe = MagicMock()
        return tag_manager

    @pytest.mark.asyncio
    async def test_flush_clears_buffer(self, mock_tag_manager: MagicMock) -> None:
        """Should clear buffer after flush."""
        recorder = HistoryRecorder(
            tag_manager=mock_tag_manager,
            db_pool=None,  # No database
            config=HistoryConfig(flush_interval=10.0),  # Long interval
        )

        # Add some records
        mock_value = MagicMock()
        mock_value.value = 25.5
        mock_value.quality = MagicMock(name="good")

        recorder._on_tag_change("temp_1", mock_value)
        recorder._on_tag_change("temp_2", mock_value)

        assert recorder.buffer_size == 2

        # Manually trigger flush
        await recorder._flush()

        # Buffer should be empty (discarded without database)
        assert recorder.buffer_size == 0

    @pytest.mark.asyncio
    async def test_flush_empty_buffer_is_noop(self, mock_tag_manager: MagicMock) -> None:
        """Should handle empty buffer gracefully."""
        recorder = HistoryRecorder(tag_manager=mock_tag_manager)

        # Should not raise
        await recorder._flush()

        assert recorder.buffer_size == 0

    @pytest.mark.asyncio
    async def test_max_buffer_triggers_flush(self, mock_tag_manager: MagicMock) -> None:
        """Should trigger flush when buffer reaches max size."""
        config = HistoryConfig(max_buffer_size=3, flush_interval=60.0)
        recorder = HistoryRecorder(
            tag_manager=mock_tag_manager,
            db_pool=None,
            config=config,
        )

        mock_value = MagicMock()
        mock_value.value = 25.5
        mock_value.quality = MagicMock(name="good")

        # Add records up to max
        recorder._on_tag_change("temp_1", mock_value)
        recorder._on_tag_change("temp_2", mock_value)

        assert recorder.buffer_size == 2

        # Adding one more should trigger async flush
        recorder._on_tag_change("temp_3", mock_value)

        # Give async task time to run
        await asyncio.sleep(0.1)

        # Buffer should be cleared by the triggered flush
        assert recorder.buffer_size == 0
