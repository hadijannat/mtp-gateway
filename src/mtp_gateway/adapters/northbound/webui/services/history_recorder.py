"""History recording service for tag values.

Records tag value changes to TimescaleDB for trending and analysis.
Uses batched inserts for efficient database operations.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from mtp_gateway.adapters.northbound.webui.database.repository import HistoryRepository

if TYPE_CHECKING:
    from mtp_gateway.adapters.northbound.webui.database.connection import DatabasePool
    from mtp_gateway.application.tag_manager import TagManager
    from mtp_gateway.domain.model.tags import TagValue

logger = structlog.get_logger(__name__)


@dataclass
class HistoryConfig:
    """Configuration for history recording."""

    # Flush interval in seconds
    flush_interval: float = 1.0

    # Maximum buffer size before forced flush
    max_buffer_size: int = 100

    # Tags to exclude from recording (e.g., high-frequency diagnostic tags)
    exclude_tags: set[str] | None = None

    # Tags to explicitly include (if set, only these are recorded)
    include_tags: set[str] | None = None


class HistoryRecorder:
    """Service that records tag values to TimescaleDB.

    Subscribes to TagManager and buffers value changes for efficient
    batch insertion into the tag_history hypertable. Configurable
    flush interval balances latency vs. database efficiency.

    Example:
        recorder = HistoryRecorder(tag_manager, db_pool, config)
        await recorder.start()
        # ... recorder now captures and stores tag changes
        await recorder.stop()
    """

    def __init__(
        self,
        tag_manager: TagManager,
        db_pool: DatabasePool | None = None,
        config: HistoryConfig | None = None,
    ) -> None:
        """Initialize the history recorder.

        Args:
            tag_manager: Tag manager to subscribe to
            db_pool: Database pool for TimescaleDB
            config: Recording configuration
        """
        self._tag_manager = tag_manager
        self._db_pool = db_pool
        self._config = config or HistoryConfig()

        # Buffer for pending records: (timestamp, tag_name, value, quality)
        self._buffer: deque[tuple[datetime, str, float | None, str]] = deque()
        self._buffer_lock = asyncio.Lock()

        # Running state
        self._running = False
        self._flush_task: asyncio.Task | None = None
        self._background_tasks: set[asyncio.Task] = set()

        # Statistics
        self._records_written = 0
        self._flush_count = 0

    async def start(self) -> None:
        """Start the history recorder service."""
        if self._running:
            return

        if not self._db_pool or not self._db_pool.is_connected:
            logger.warning("History recorder started without database - records will be discarded")

        # Subscribe to tag changes
        self._tag_manager.subscribe(self._on_tag_change)

        # Start flush task
        self._flush_task = asyncio.create_task(self._periodic_flush())

        self._running = True
        logger.info(
            "History recorder started",
            flush_interval=self._config.flush_interval,
            max_buffer=self._config.max_buffer_size,
        )

    async def stop(self) -> None:
        """Stop the history recorder service."""
        if not self._running:
            return

        # Unsubscribe from tag changes
        self._tag_manager.unsubscribe(self._on_tag_change)

        # Cancel flush task
        if self._flush_task:
            self._flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._flush_task
            self._flush_task = None

        # Final flush
        await self._flush()

        self._running = False
        logger.info(
            "History recorder stopped",
            total_records=self._records_written,
            total_flushes=self._flush_count,
        )

    def _on_tag_change(self, tag_name: str, value: TagValue) -> None:
        """Handle tag value changes from TagManager.

        This is called synchronously by TagManager, so we buffer
        the record for async processing.

        Args:
            tag_name: Changed tag name
            value: New tag value
        """
        # Check include/exclude filters
        if self._config.include_tags and tag_name not in self._config.include_tags:
            return
        if self._config.exclude_tags and tag_name in self._config.exclude_tags:
            return

        # Add to buffer (thread-safe append)
        record = (
            datetime.now(UTC),
            tag_name,
            float(value.value) if value.value is not None else None,
            value.quality.name if hasattr(value.quality, "name") else str(value.quality),
        )
        self._buffer.append(record)

        # Check for forced flush
        if len(self._buffer) >= self._config.max_buffer_size:
            task = asyncio.create_task(self._flush())
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

    async def _periodic_flush(self) -> None:
        """Periodically flush buffer to database."""
        while True:
            try:
                await asyncio.sleep(self._config.flush_interval)
                await self._flush()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in periodic history flush", error=str(e))

    async def _flush(self) -> None:
        """Flush buffered records to database."""
        if not self._buffer:
            return

        async with self._buffer_lock:
            if not self._buffer:
                return

            # Extract all records from buffer
            records = list(self._buffer)
            self._buffer.clear()

        if not records:
            return

        # Write to database
        if self._db_pool and self._db_pool.is_connected:
            try:
                repo = HistoryRepository(self._db_pool.pool)
                count = await repo.insert_batch(records)

                self._records_written += count
                self._flush_count += 1

                logger.debug(
                    "History records flushed",
                    count=count,
                    total=self._records_written,
                )

            except Exception as e:
                logger.error(
                    "Failed to flush history records",
                    error=str(e),
                    count=len(records),
                )
                # Re-queue records on failure (front of queue)
                async with self._buffer_lock:
                    for record in reversed(records):
                        self._buffer.appendleft(record)
        else:
            # No database - just count the discarded records
            logger.debug(
                "History records discarded (no database)",
                count=len(records),
            )

    async def record_value(
        self,
        tag_name: str,
        value: float | None,
        quality: str = "good",
        timestamp: datetime | None = None,
    ) -> None:
        """Manually record a single value.

        Can be used for explicit history recording outside of
        subscription-based capture.

        Args:
            tag_name: Tag name
            value: Tag value
            quality: Quality indicator
            timestamp: Optional timestamp (defaults to now)
        """
        record = (
            timestamp or datetime.now(UTC),
            tag_name,
            value,
            quality,
        )
        self._buffer.append(record)

    @property
    def is_running(self) -> bool:
        """Check if recorder is running."""
        return self._running

    @property
    def buffer_size(self) -> int:
        """Get current buffer size."""
        return len(self._buffer)

    @property
    def records_written(self) -> int:
        """Get total records written to database."""
        return self._records_written

    @property
    def flush_count(self) -> int:
        """Get total number of flushes performed."""
        return self._flush_count
