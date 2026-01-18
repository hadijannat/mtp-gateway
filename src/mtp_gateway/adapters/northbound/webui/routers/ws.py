"""WebSocket endpoint router.

Provides WebSocket endpoint for real-time updates.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Query, Request, WebSocket, WebSocketDisconnect
from jose import JWTError

from mtp_gateway.adapters.northbound.webui.security.jwt import TokenService
from mtp_gateway.adapters.northbound.webui.websocket.manager import WebSocketManager

logger = structlog.get_logger(__name__)

router = APIRouter()


def get_ws_manager(request: Request) -> WebSocketManager:
    """Get WebSocket manager from app state."""
    return request.app.state.ws_manager


def get_token_service(request: Request) -> TokenService:
    """Get token service from app state."""
    return request.app.state.token_service


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token"),
) -> None:
    """WebSocket endpoint for real-time updates.

    Connect with JWT token as query parameter:
    ws://host:port/api/v1/ws?token=<jwt_access_token>

    Protocol:
    - Subscribe: {"type": "subscribe", "payload": {"channel": "tags", "tags": ["tag1"]}}
    - Unsubscribe: {"type": "unsubscribe", "payload": {"channel": "tags"}}
    - Ping: {"type": "ping", "payload": {}}

    Server sends:
    - tag_update: {"type": "tag_update", "payload": {"tag_name": "...", "value": ..., ...}}
    - state_change: {"type": "state_change", "payload": {"service_name": "...", ...}}
    - alarm: {"type": "alarm", "payload": {"action": "raised", "alarm": {...}}}
    """
    # Get dependencies from app state
    ws_manager: WebSocketManager = websocket.app.state.ws_manager
    token_service: TokenService = websocket.app.state.token_service

    # Validate token
    try:
        payload = token_service.decode_token(token)

        if payload.type != "access":
            await websocket.close(code=4001, reason="Invalid token type")
            return

    except JWTError as e:
        logger.warning("WebSocket auth failed", error=str(e))
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    # Accept connection
    connection_id = await ws_manager.connect(
        websocket=websocket,
        user_id=0,  # Would come from database lookup
        username=payload.sub,
        permissions=payload.permissions,
    )

    try:
        # Run message loop
        await ws_manager.run_connection(connection_id)

    except WebSocketDisconnect:
        logger.debug("WebSocket disconnected", connection_id=connection_id)

    except Exception:
        logger.exception("WebSocket error", connection_id=connection_id)

    finally:
        await ws_manager.disconnect(connection_id)
