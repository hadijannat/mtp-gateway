"""WebSocket connection manager for real-time updates.

Manages WebSocket connections with authentication, subscriptions,
and message routing to connected clients.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

import structlog
from fastapi import WebSocket, WebSocketDisconnect

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

logger = structlog.get_logger(__name__)


class MessageType(str, Enum):
    """WebSocket message types."""

    # Client -> Server
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    PING = "ping"

    # Server -> Client
    TAG_UPDATE = "tag_update"
    STATE_CHANGE = "state_change"
    ALARM = "alarm"
    ERROR = "error"
    PONG = "pong"
    SUBSCRIBED = "subscribed"
    UNSUBSCRIBED = "unsubscribed"


class Channel(str, Enum):
    """Available subscription channels."""

    TAGS = "tags"
    SERVICES = "services"
    ALARMS = "alarms"
    ALL = "all"


@dataclass
class Subscription:
    """Subscription to a channel with optional filters.

    Attributes:
        channel: Channel to subscribe to
        filter_tags: Optional list of tag names to filter (for tags channel)
        filter_services: Optional list of service names to filter
    """

    channel: Channel
    filter_tags: list[str] = field(default_factory=list)
    filter_services: list[str] = field(default_factory=list)


@dataclass
class Connection:
    """Represents a WebSocket connection with metadata.

    Attributes:
        websocket: FastAPI WebSocket instance
        user_id: Authenticated user ID
        username: Authenticated username
        permissions: User's permissions
        subscriptions: Active subscriptions
        created_at: Connection timestamp
    """

    websocket: WebSocket
    user_id: int
    username: str
    permissions: list[str]
    subscriptions: dict[Channel, Subscription] = field(default_factory=dict)
    created_at: float = field(default_factory=lambda: asyncio.get_event_loop().time())


class WebSocketManager:
    """Manages WebSocket connections and message broadcasting.

    Handles:
    - Connection lifecycle (connect, disconnect)
    - Authentication validation
    - Subscription management
    - Message routing based on subscriptions
    """

    def __init__(self) -> None:
        """Initialize the WebSocket manager."""
        self._connections: dict[str, Connection] = {}  # connection_id -> Connection
        self._lock = asyncio.Lock()
        self._message_handlers: dict[str, Callable[..., Coroutine[Any, Any, None]]] = {}

    @property
    def connection_count(self) -> int:
        """Return the number of active connections."""
        return len(self._connections)

    def _generate_connection_id(self, websocket: WebSocket) -> str:
        """Generate a unique connection ID."""
        # Use client host:port as connection ID
        client = websocket.client
        if client:
            return f"{client.host}:{client.port}"
        return str(id(websocket))

    async def connect(
        self,
        websocket: WebSocket,
        user_id: int,
        username: str,
        permissions: list[str],
    ) -> str:
        """Accept a new WebSocket connection.

        Args:
            websocket: FastAPI WebSocket instance
            user_id: Authenticated user ID
            username: Authenticated username
            permissions: User's permissions

        Returns:
            Connection ID
        """
        await websocket.accept()

        connection_id = self._generate_connection_id(websocket)

        async with self._lock:
            self._connections[connection_id] = Connection(
                websocket=websocket,
                user_id=user_id,
                username=username,
                permissions=permissions,
            )

        logger.info(
            "WebSocket connected",
            connection_id=connection_id,
            username=username,
            user_id=user_id,
        )

        return connection_id

    async def disconnect(self, connection_id: str) -> None:
        """Remove a disconnected WebSocket.

        Args:
            connection_id: Connection to remove
        """
        async with self._lock:
            if connection_id in self._connections:
                conn = self._connections.pop(connection_id)
                logger.info(
                    "WebSocket disconnected",
                    connection_id=connection_id,
                    username=conn.username,
                )

    async def subscribe(
        self,
        connection_id: str,
        channel: Channel,
        filter_tags: list[str] | None = None,
        filter_services: list[str] | None = None,
    ) -> bool:
        """Subscribe a connection to a channel.

        Args:
            connection_id: Connection to subscribe
            channel: Channel to subscribe to
            filter_tags: Optional tag filter for tags channel
            filter_services: Optional service filter

        Returns:
            True if subscription was added
        """
        async with self._lock:
            conn = self._connections.get(connection_id)
            if not conn:
                return False

            subscription = Subscription(
                channel=channel,
                filter_tags=filter_tags or [],
                filter_services=filter_services or [],
            )
            conn.subscriptions[channel] = subscription

            logger.debug(
                "Subscription added",
                connection_id=connection_id,
                channel=channel.value,
                filter_tags=filter_tags,
            )

            return True

    async def unsubscribe(self, connection_id: str, channel: Channel) -> bool:
        """Unsubscribe a connection from a channel.

        Args:
            connection_id: Connection to unsubscribe
            channel: Channel to unsubscribe from

        Returns:
            True if subscription was removed
        """
        async with self._lock:
            conn = self._connections.get(connection_id)
            if not conn:
                return False

            if channel in conn.subscriptions:
                del conn.subscriptions[channel]
                logger.debug(
                    "Subscription removed",
                    connection_id=connection_id,
                    channel=channel.value,
                )
                return True

            return False

    async def send_personal(
        self,
        connection_id: str,
        message_type: MessageType,
        payload: dict[str, Any],
    ) -> bool:
        """Send a message to a specific connection.

        Args:
            connection_id: Target connection
            message_type: Type of message
            payload: Message payload

        Returns:
            True if message was sent
        """
        conn = self._connections.get(connection_id)
        if not conn:
            return False

        try:
            await conn.websocket.send_json({
                "type": message_type.value,
                "payload": payload,
            })
            return True
        except Exception:
            logger.exception(
                "Failed to send message",
                connection_id=connection_id,
            )
            return False

    async def broadcast_to_channel(
        self,
        channel: Channel,
        message_type: MessageType,
        payload: dict[str, Any],
        filter_key: str | None = None,
    ) -> int:
        """Broadcast a message to all subscribers of a channel.

        Args:
            channel: Target channel
            message_type: Type of message
            payload: Message payload
            filter_key: Optional key for filtering (tag_name or service_name)

        Returns:
            Number of connections that received the message
        """
        sent_count = 0
        failed_connections: list[str] = []

        message = {
            "type": message_type.value,
            "payload": payload,
        }

        async with self._lock:
            for conn_id, conn in self._connections.items():
                # Check if subscribed to channel or "all"
                subscription = conn.subscriptions.get(channel) or conn.subscriptions.get(
                    Channel.ALL
                )
                if not subscription:
                    continue

                # Apply filter if specified
                if filter_key:
                    if channel == Channel.TAGS and subscription.filter_tags:
                        if filter_key not in subscription.filter_tags:
                            continue
                    elif channel == Channel.SERVICES and subscription.filter_services:
                        if filter_key not in subscription.filter_services:
                            continue

                try:
                    await conn.websocket.send_json(message)
                    sent_count += 1
                except Exception:
                    logger.warning(
                        "Failed to send to connection",
                        connection_id=conn_id,
                    )
                    failed_connections.append(conn_id)

        # Clean up failed connections outside the lock
        for conn_id in failed_connections:
            await self.disconnect(conn_id)

        return sent_count

    async def broadcast_all(
        self,
        message_type: MessageType,
        payload: dict[str, Any],
    ) -> int:
        """Broadcast a message to all connected clients.

        Args:
            message_type: Type of message
            payload: Message payload

        Returns:
            Number of connections that received the message
        """
        sent_count = 0
        failed_connections: list[str] = []

        message = {
            "type": message_type.value,
            "payload": payload,
        }

        async with self._lock:
            for conn_id, conn in self._connections.items():
                try:
                    await conn.websocket.send_json(message)
                    sent_count += 1
                except Exception:
                    failed_connections.append(conn_id)

        for conn_id in failed_connections:
            await self.disconnect(conn_id)

        return sent_count

    async def handle_message(
        self,
        connection_id: str,
        message: dict[str, Any],
    ) -> None:
        """Handle an incoming WebSocket message.

        Args:
            connection_id: Source connection
            message: Parsed JSON message
        """
        msg_type = message.get("type", "")
        payload = message.get("payload", {})

        if msg_type == MessageType.PING.value:
            await self.send_personal(connection_id, MessageType.PONG, {})

        elif msg_type == MessageType.SUBSCRIBE.value:
            channel_str = payload.get("channel", "")
            try:
                channel = Channel(channel_str)
                await self.subscribe(
                    connection_id,
                    channel,
                    filter_tags=payload.get("tags"),
                    filter_services=payload.get("services"),
                )
                await self.send_personal(
                    connection_id,
                    MessageType.SUBSCRIBED,
                    {"channel": channel_str},
                )
            except ValueError:
                await self.send_personal(
                    connection_id,
                    MessageType.ERROR,
                    {"message": f"Unknown channel: {channel_str}"},
                )

        elif msg_type == MessageType.UNSUBSCRIBE.value:
            channel_str = payload.get("channel", "")
            try:
                channel = Channel(channel_str)
                await self.unsubscribe(connection_id, channel)
                await self.send_personal(
                    connection_id,
                    MessageType.UNSUBSCRIBED,
                    {"channel": channel_str},
                )
            except ValueError:
                await self.send_personal(
                    connection_id,
                    MessageType.ERROR,
                    {"message": f"Unknown channel: {channel_str}"},
                )

        else:
            await self.send_personal(
                connection_id,
                MessageType.ERROR,
                {"message": f"Unknown message type: {msg_type}"},
            )

    async def run_connection(self, connection_id: str) -> None:
        """Run the message loop for a connection.

        Handles incoming messages until disconnection.

        Args:
            connection_id: Connection to handle
        """
        conn = self._connections.get(connection_id)
        if not conn:
            return

        try:
            while True:
                data = await conn.websocket.receive_json()
                await self.handle_message(connection_id, data)
        except WebSocketDisconnect:
            pass
        finally:
            await self.disconnect(connection_id)
