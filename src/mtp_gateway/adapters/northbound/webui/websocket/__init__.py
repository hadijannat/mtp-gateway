"""WebSocket module for real-time updates.

Provides:
- Connection management with authentication
- Channel-based subscriptions
- Event broadcasting from application layer
"""

from mtp_gateway.adapters.northbound.webui.websocket.broadcaster import (
    EventBroadcaster,
    create_broadcaster_with_subscriptions,
)
from mtp_gateway.adapters.northbound.webui.websocket.manager import (
    Channel,
    Connection,
    MessageType,
    Subscription,
    WebSocketManager,
)

__all__ = [
    "Channel",
    "Connection",
    "EventBroadcaster",
    "MessageType",
    "Subscription",
    "WebSocketManager",
    "create_broadcaster_with_subscriptions",
]
