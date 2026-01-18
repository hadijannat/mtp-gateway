"""WebUI adapter for MTP Gateway.

Provides:
- REST API for configuration and monitoring
- WebSocket support for real-time updates
- JWT-based authentication with RBAC
"""

from mtp_gateway.adapters.northbound.webui.server import MTPWebUIServer

__all__ = [
    "MTPWebUIServer",
]
