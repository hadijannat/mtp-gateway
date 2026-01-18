"""API routers for WebUI.

Provides FastAPI routers for all API endpoints:
- auth: Authentication (login, refresh, logout)
- tags: Tag read/write operations
- services: Service state and commands
- alarms: Alarm management
- history: Tag history queries
- health: Health check endpoints
- ws: WebSocket endpoint
"""

from mtp_gateway.adapters.northbound.webui.routers import (
    auth,
    tags,
    services,
    alarms,
    history,
    health,
    ws,
)

__all__ = [
    "auth",
    "tags",
    "services",
    "alarms",
    "history",
    "health",
    "ws",
]
