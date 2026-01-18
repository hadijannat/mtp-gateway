"""Event broadcaster for WebSocket updates.

Bridges TagManager and ServiceManager events to WebSocket clients.
Handles rate limiting and batching for efficient updates.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from mtp_gateway.adapters.northbound.webui.websocket.manager import (
    Channel,
    MessageType,
    WebSocketManager,
)

if TYPE_CHECKING:
    from mtp_gateway.application.service_manager import ServiceManager
    from mtp_gateway.application.tag_manager import TagManager
    from mtp_gateway.domain.model.tags import TagValue

logger = structlog.get_logger(__name__)


class EventBroadcaster:
    """Broadcasts events from application layer to WebSocket clients.

    Subscribes to TagManager and ServiceManager for updates,
    formats them as WebSocket messages, and broadcasts to clients.

    Includes rate limiting to prevent overwhelming clients with
    high-frequency tag updates.
    """

    def __init__(
        self,
        ws_manager: WebSocketManager,
        min_update_interval_ms: int = 100,
    ) -> None:
        """Initialize the event broadcaster.

        Args:
            ws_manager: WebSocket manager for broadcasting
            min_update_interval_ms: Minimum interval between updates per tag
        """
        self._ws_manager = ws_manager
        self._min_interval_ms = min_update_interval_ms
        self._last_update: dict[str, float] = {}  # tag_name -> timestamp
        self._pending_updates: dict[str, dict[str, Any]] = {}  # tag_name -> payload
        self._update_task: asyncio.Task[None] | None = None
        self._background_tasks: set[asyncio.Task] = set()
        self._running = False

    async def start(self) -> None:
        """Start the broadcaster background tasks."""
        if self._running:
            return

        self._running = True
        self._update_task = asyncio.create_task(self._flush_pending_updates())

        logger.info("Event broadcaster started")

    async def stop(self) -> None:
        """Stop the broadcaster and cleanup."""
        self._running = False

        if self._update_task:
            self._update_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._update_task

        logger.info("Event broadcaster stopped")

    def _track_task(self, task: asyncio.Task) -> None:
        """Track a background task to avoid garbage collection."""
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _flush_pending_updates(self) -> None:
        """Background task to flush rate-limited updates."""
        while self._running:
            await asyncio.sleep(self._min_interval_ms / 1000)

            if not self._pending_updates:
                continue

            # Copy and clear pending updates
            updates = self._pending_updates.copy()
            self._pending_updates.clear()

            # Broadcast each pending update
            for tag_name, payload in updates.items():
                await self._ws_manager.broadcast_to_channel(
                    Channel.TAGS,
                    MessageType.TAG_UPDATE,
                    payload,
                    filter_key=tag_name,
                )

    def on_tag_change(self, tag_name: str, value: TagValue) -> None:
        """Handle tag value change from TagManager.

        Rate limits updates to prevent flooding clients.

        Args:
            tag_name: Changed tag name
            value: New tag value
        """
        now = datetime.now(UTC).timestamp()
        last = self._last_update.get(tag_name, 0)

        payload = {
            "tag_name": tag_name,
            "value": value.value,
            "quality": (
                value.quality.value if hasattr(value.quality, "value") else str(value.quality)
            ),
            "timestamp": (
                value.timestamp.isoformat() if value.timestamp else datetime.now(UTC).isoformat()
            ),
        }

        # If enough time has passed, broadcast immediately
        if (now - last) * 1000 >= self._min_interval_ms:
            self._last_update[tag_name] = now
            task = asyncio.create_task(
                self._ws_manager.broadcast_to_channel(
                    Channel.TAGS,
                    MessageType.TAG_UPDATE,
                    payload,
                    filter_key=tag_name,
                )
            )
            self._track_task(task)
        else:
            # Queue for batched update
            self._pending_updates[tag_name] = payload

    def on_state_change(
        self,
        service_name: str,
        from_state: str,
        to_state: str,
    ) -> None:
        """Handle service state change from ServiceManager.

        State changes are always broadcast immediately.

        Args:
            service_name: Service that changed
            from_state: Previous state name
            to_state: New state name
        """
        payload = {
            "service_name": service_name,
            "from_state": from_state,
            "to_state": to_state,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        task = asyncio.create_task(
            self._ws_manager.broadcast_to_channel(
                Channel.SERVICES,
                MessageType.STATE_CHANGE,
                payload,
                filter_key=service_name,
            )
        )
        self._track_task(task)

        logger.debug(
            "Broadcast state change",
            service=service_name,
            from_state=from_state,
            to_state=to_state,
        )

    def on_alarm(
        self,
        action: str,
        alarm_id: int,
        alarm_data: dict[str, Any],
    ) -> None:
        """Handle alarm event.

        Alarms are always broadcast immediately.

        Args:
            action: Alarm action (raised, acknowledged, cleared, shelved)
            alarm_id: Database alarm ID
            alarm_data: Alarm details
        """
        payload = {
            "action": action,
            "alarm_id": alarm_id,
            "alarm": alarm_data,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        task = asyncio.create_task(
            self._ws_manager.broadcast_to_channel(
                Channel.ALARMS,
                MessageType.ALARM,
                payload,
            )
        )
        self._track_task(task)

        logger.debug(
            "Broadcast alarm",
            action=action,
            alarm_id=alarm_id,
        )

    def on_alarm_change(
        self,
        action: str,
        alarm_id: str,
        source: str,
        priority: int | None = None,
        message: str | None = None,
    ) -> None:
        """Handle alarm state change from AlarmDetector.

        Simplified method for detector-generated alarm events.
        Alarms are always broadcast immediately.

        Args:
            action: Alarm action (raised, cleared)
            alarm_id: Logical alarm identifier
            source: Alarm source (data assembly name)
            priority: Alarm priority (1-4), optional
            message: Alarm message, optional
        """
        payload = {
            "action": action,
            "alarm_id": alarm_id,
            "source": source,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        if priority is not None:
            payload["priority"] = priority
        if message is not None:
            payload["message"] = message

        task = asyncio.create_task(
            self._ws_manager.broadcast_to_channel(
                Channel.ALARMS,
                MessageType.ALARM,
                payload,
            )
        )
        self._track_task(task)

        logger.debug(
            "Broadcast alarm change",
            action=action,
            alarm_id=alarm_id,
            source=source,
        )


def create_broadcaster_with_subscriptions(
    tag_manager: TagManager,
    service_manager: ServiceManager,
    ws_manager: WebSocketManager,
    min_update_interval_ms: int = 100,
) -> EventBroadcaster:
    """Create an EventBroadcaster and wire up subscriptions.

    Convenience function to create a broadcaster and connect it
    to the application layer managers.

    Args:
        tag_manager: TagManager to subscribe to
        service_manager: ServiceManager to subscribe to
        ws_manager: WebSocket manager for broadcasting
        min_update_interval_ms: Minimum update interval

    Returns:
        Configured EventBroadcaster
    """
    broadcaster = EventBroadcaster(
        ws_manager=ws_manager,
        min_update_interval_ms=min_update_interval_ms,
    )

    # Subscribe to tag changes
    tag_manager.subscribe(broadcaster.on_tag_change)

    # Subscribe to state changes
    service_manager.subscribe(broadcaster.on_state_change)

    logger.info(
        "Broadcaster subscribed to managers",
        min_update_interval_ms=min_update_interval_ms,
    )

    return broadcaster
