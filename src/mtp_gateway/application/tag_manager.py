"""Tag Manager for MTP Gateway.

Orchestrates tag polling from southbound connectors and maintains
the current state of all tags. Supports both periodic polling and
on-demand reads, with event-driven updates for OPC UA subscriptions.
"""

from __future__ import annotations

import asyncio
import inspect
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

import structlog

from mtp_gateway.domain.model.tags import (
    DataType,
    Quality,
    ScaleConfig,
    TagDefinition,
    TagState,
    TagValue,
)

if TYPE_CHECKING:
    from mtp_gateway.adapters.persistence import PersistenceRepository
    from mtp_gateway.adapters.southbound.base import ConnectorPort
    from mtp_gateway.config.schema import TagConfig
    from mtp_gateway.domain.rules.safety import SafetyController

logger = structlog.get_logger(__name__)


# Type alias for value change callbacks
ValueChangeCallback = Callable[[str, TagValue], None]


@dataclass
class TagGroup:
    """Group of tags polled together from the same connector."""

    connector_name: str
    addresses: list[str]
    poll_interval_ms: int
    tags: list[TagDefinition]


class TagManager:
    """Manages tag polling and state for all configured tags.

    Responsibilities:
    - Organize tags by connector for efficient polling
    - Poll connectors at configured intervals
    - Apply scaling transformations
    - Track tag state and quality
    - Notify subscribers on value changes
    """

    def __init__(
        self,
        connectors: dict[str, ConnectorPort],
        tags: list[TagConfig],
        persistence: PersistenceRepository | None = None,
        safety: SafetyController | None = None,
    ) -> None:
        """Initialize the tag manager.

        Args:
            connectors: Dictionary of connector instances by name
            tags: List of tag configurations
            persistence: Optional PersistenceRepository for tag history
            safety: Optional SafetyController for write validation
        """
        self._connectors = connectors
        self._persistence = persistence
        self._safety = safety
        self._tags: dict[str, TagState] = {}
        self._groups: dict[str, TagGroup] = {}
        self._poll_tasks: dict[str, asyncio.Task[None]] = {}
        self._running = False
        self._subscribers: list[ValueChangeCallback] = []
        self._lock = asyncio.Lock()

        # Build tag definitions and groups
        self._build_tags(tags)

    def _build_tags(self, tag_configs: list[TagConfig]) -> None:
        """Build tag definitions and organize into groups."""
        # Group tags by connector
        connector_tags: dict[str, list[TagConfig]] = defaultdict(list)
        for config in tag_configs:
            connector_tags[config.connector].append(config)

        # Create tag definitions and groups
        for connector_name, configs in connector_tags.items():
            if connector_name not in self._connectors:
                logger.warning(
                    "Tag references unknown connector",
                    connector=connector_name,
                )
                continue

            tags: list[TagDefinition] = []
            addresses: list[str] = []

            for config in configs:
                # Convert config to domain model
                scale = None
                if config.scale:
                    scale = ScaleConfig(
                        gain=config.scale.gain,
                        offset=config.scale.offset,
                    )

                tag_def = TagDefinition(
                    name=config.name,
                    connector=config.connector,
                    address=config.address,
                    datatype=DataType(config.datatype.value),
                    writable=config.writable,
                    scale=scale,
                    unit=config.unit,
                    description=config.description,
                    byte_order=config.byte_order.value,
                    word_order=config.word_order.value,
                )

                tags.append(tag_def)
                addresses.append(config.address)

                # Create tag state
                self._tags[config.name] = TagState(definition=tag_def)

            # Create group for this connector
            connector = self._connectors[connector_name]
            poll_interval = getattr(connector, "_config", None)
            poll_interval_ms = poll_interval.poll_interval_ms if poll_interval else 1000

            self._groups[connector_name] = TagGroup(
                connector_name=connector_name,
                addresses=addresses,
                poll_interval_ms=poll_interval_ms,
                tags=tags,
            )

        logger.info(
            "Tag manager initialized",
            total_tags=len(self._tags),
            connectors=list(self._groups.keys()),
        )

    async def start(self) -> None:
        """Start polling all tag groups."""
        if self._running:
            return

        self._running = True
        logger.info("Starting tag manager")

        for connector_name, group in self._groups.items():
            task = asyncio.create_task(
                self._poll_loop(connector_name, group),
                name=f"poll_{connector_name}",
            )
            self._poll_tasks[connector_name] = task

    async def stop(self) -> None:
        """Stop all polling tasks."""
        if not self._running:
            return

        self._running = False
        logger.info("Stopping tag manager")

        # Cancel all poll tasks
        for task in self._poll_tasks.values():
            task.cancel()

        # Wait for cancellation
        if self._poll_tasks:
            await asyncio.gather(*self._poll_tasks.values(), return_exceptions=True)

        self._poll_tasks.clear()
        logger.info("Tag manager stopped")

    async def _poll_loop(self, connector_name: str, group: TagGroup) -> None:
        """Polling loop for a single connector."""
        connector = self._connectors[connector_name]
        interval = group.poll_interval_ms / 1000

        logger.debug(
            "Starting poll loop",
            connector=connector_name,
            interval_ms=group.poll_interval_ms,
            tag_count=len(group.addresses),
        )

        while self._running:
            try:
                health = connector.health_status()
                health_state = getattr(health, "state", None)
                is_connected = getattr(health_state, "value", None) == "connected"
                if not is_connected or getattr(health, "consecutive_errors", 0) > 0:
                    reconnect = getattr(connector, "reconnect", None)
                    if callable(reconnect):
                        await reconnect()

                # Read all tags for this connector
                read_tag_values = getattr(connector, "read_tag_values", None)
                if read_tag_values and inspect.iscoroutinefunction(read_tag_values):
                    values_by_tag = await read_tag_values(group.tags)
                else:
                    values_by_addr = await connector.read_tags(group.addresses)
                    values_by_tag = {
                        tag_def.name: values_by_addr.get(tag_def.address) for tag_def in group.tags
                    }

                # Update tag states
                for tag_def in group.tags:
                    tag_value = values_by_tag.get(tag_def.name)
                    if tag_value is not None:
                        # Apply scaling if configured
                        if tag_def.scale and isinstance(tag_value.value, (int, float)):
                            scaled = tag_def.apply_scale(tag_value.value)
                            tag_value = TagValue(
                                value=scaled,
                                timestamp=tag_value.timestamp,
                                quality=tag_value.quality,
                                source_timestamp=tag_value.source_timestamp,
                            )

                        # Update state
                        tag_state = self._tags.get(tag_def.name)
                        if tag_state:
                            tag_state.update(tag_value)
                            self._notify_subscribers(tag_def.name, tag_value)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    "Poll loop error",
                    connector=connector_name,
                    error=str(e),
                )
                # Mark all tags as bad quality
                await self._mark_tags_bad(group.tags, str(e))

            # Wait for next poll interval
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break

    async def _mark_tags_bad(self, tags: list[TagDefinition], error: str) -> None:
        """Mark tags as bad quality due to communication failure."""
        logger.warning(
            "Marking tags bad after poll failure",
            tag_count=len(tags),
            error=error,
        )
        now = datetime.now(UTC)
        for tag_def in tags:
            tag_state = self._tags.get(tag_def.name)
            if tag_state:
                # Use last good value if available, with uncertain quality
                if tag_state.last_good_value:
                    bad_value = TagValue(
                        value=tag_state.last_good_value.value,
                        timestamp=now,
                        quality=Quality.UNCERTAIN_NO_COMM_LAST_USABLE,
                        source_timestamp=tag_state.last_good_value.timestamp,
                    )
                else:
                    bad_value = TagValue(
                        value=0,
                        timestamp=now,
                        quality=Quality.BAD_NO_COMMUNICATION,
                    )
                tag_state.update(bad_value)
                self._notify_subscribers(tag_def.name, bad_value)

    def _notify_subscribers(self, tag_name: str, value: TagValue) -> None:
        """Notify all subscribers of a value change."""
        for callback in self._subscribers:
            try:
                callback(tag_name, value)
            except Exception as e:
                logger.warning(
                    "Subscriber callback error",
                    tag=tag_name,
                    error=str(e),
                )

    def subscribe(self, callback: ValueChangeCallback) -> None:
        """Subscribe to value changes for all tags."""
        self._subscribers.append(callback)

    def unsubscribe(self, callback: ValueChangeCallback) -> None:
        """Unsubscribe from value changes."""
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def get_tag(self, name: str) -> TagState | None:
        """Get current state for a tag."""
        return self._tags.get(name)

    def get_value(self, name: str) -> TagValue | None:
        """Get current value for a tag."""
        state = self._tags.get(name)
        return state.current_value if state else None

    def get_all_tags(self) -> dict[str, TagState]:
        """Get all tag states."""
        return self._tags.copy()

    def get_all_tag_names(self) -> list[str]:
        """Get all tag names."""
        return sorted(self._tags.keys())

    async def read_tag(self, name: str) -> TagValue | None:
        """Read a tag immediately (bypass polling cache).

        Args:
            name: Tag name

        Returns:
            Current tag value or None if tag not found
        """
        state = self._tags.get(name)
        if not state:
            logger.warning("Tag not found", tag=name)
            return None

        tag_def = state.definition
        connector = self._connectors.get(tag_def.connector)
        if not connector:
            logger.warning("Connector not found", connector=tag_def.connector)
            return None

        # Read from connector
        read_tag_values = getattr(connector, "read_tag_values", None)
        if read_tag_values and inspect.iscoroutinefunction(read_tag_values):
            values = cast("dict[str, TagValue]", await read_tag_values([tag_def]))
            tag_value = values.get(tag_def.name)
        else:
            values = await connector.read_tags([tag_def.address])
            tag_value = values.get(tag_def.address)

        if tag_value is not None:
            # Apply scaling
            if tag_def.scale and isinstance(tag_value.value, (int, float)):
                scaled = tag_def.apply_scale(tag_value.value)
                tag_value = TagValue(
                    value=scaled,
                    timestamp=tag_value.timestamp,
                    quality=tag_value.quality,
                )

            state.update(tag_value)
            self._notify_subscribers(name, tag_value)
            return tag_value

        return None

    async def write_tag(self, name: str, value: Any) -> bool:  # noqa: PLR0911
        """Write a value to a tag.

        Performs safety checks before writing:
        1. Tag must exist and be writable
        2. If SafetyController configured, tag must be in allowlist
        3. If rate limiter configured, must be within rate limit

        Args:
            name: Tag name
            value: Value to write

        Returns:
            True if write succeeded, False otherwise
        """
        state = self._tags.get(name)
        if not state:
            logger.warning("Tag not found for write", tag=name)
            return False

        tag_def = state.definition
        if not tag_def.writable:
            logger.warning("Tag is not writable", tag=name)
            return False

        # Safety validation (if controller configured)
        if self._safety:
            validation = self._safety.validate_write(name)
            if not validation.allowed:
                logger.warning(
                    "Write blocked by safety",
                    tag=name,
                    reason=validation.reason,
                )
                return False

            if not self._safety.check_rate_limit():
                logger.warning("Write rate limit exceeded", tag=name)
                return False

        connector = self._connectors.get(tag_def.connector)
        if not connector:
            logger.warning("Connector not found", connector=tag_def.connector)
            return False

        # Reverse scale if configured
        write_value = value
        if tag_def.scale and isinstance(value, (int, float)):
            write_value = tag_def.reverse_scale(value)

        # Coerce to expected type
        try:
            expected_type = tag_def.datatype.python_type()
            write_value = expected_type(write_value)
        except (TypeError, ValueError):
            logger.warning(
                "Failed to coerce write value",
                tag=name,
                expected_type=tag_def.datatype.value,
                value=write_value,
            )
            return False

        # Write to connector
        write_tag_value = getattr(connector, "write_tag_value", None)
        if write_tag_value and inspect.iscoroutinefunction(write_tag_value):
            success = await write_tag_value(tag_def, write_value)
        else:
            success = await connector.write_tag(tag_def.address, write_value)
        if success:
            state.write_count += 1
            # Read back the value to confirm
            await self.read_tag(name)

        return cast("bool", success)

    def get_tags_by_connector(self, connector_name: str) -> list[TagState]:
        """Get all tags for a specific connector."""
        return [
            state for state in self._tags.values() if state.definition.connector == connector_name
        ]

    def get_statistics(self) -> dict[str, Any]:
        """Get tag manager statistics."""
        total_reads = sum(t.read_count for t in self._tags.values())
        total_writes = sum(t.write_count for t in self._tags.values())
        total_errors = sum(t.error_count for t in self._tags.values())

        good_count = sum(1 for t in self._tags.values() if t.quality.is_good())
        bad_count = sum(1 for t in self._tags.values() if t.quality.is_bad())

        return {
            "total_tags": len(self._tags),
            "total_reads": total_reads,
            "total_writes": total_writes,
            "total_errors": total_errors,
            "good_quality_count": good_count,
            "bad_quality_count": bad_count,
            "connectors": list(self._groups.keys()),
        }
