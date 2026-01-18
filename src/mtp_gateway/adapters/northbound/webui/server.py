"""FastAPI WebUI Server for MTP Gateway.

Provides REST API and WebSocket endpoints for browser-based HMI.
Follows the same lifecycle pattern as the OPC UA server.
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mtp_gateway.adapters.northbound.webui.database.connection import (
    DatabasePool,
    set_db_pool,
)
from mtp_gateway.adapters.northbound.webui.routers import (
    alarms,
    auth,
    health,
    history,
    services,
    tags,
    ws,
)
from mtp_gateway.adapters.northbound.webui.security.jwt import TokenService
from mtp_gateway.adapters.northbound.webui.services.alarm_detector import AlarmDetector
from mtp_gateway.adapters.northbound.webui.services.history_recorder import (
    HistoryConfig,
    HistoryRecorder,
)
from mtp_gateway.adapters.northbound.webui.websocket.broadcaster import EventBroadcaster
from mtp_gateway.adapters.northbound.webui.websocket.manager import WebSocketManager

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from mtp_gateway.application.service_manager import ServiceManager
    from mtp_gateway.application.tag_manager import TagManager
    from mtp_gateway.config.schema import GatewayConfig
    from mtp_gateway.domain.state_machine.packml import PackMLState

logger = structlog.get_logger(__name__)


class MTPWebUIServer:
    """FastAPI server exposing REST API and WebSocket for MTP Gateway.

    Provides:
    - REST API for tag read/write, service commands, alarms, history
    - WebSocket for real-time updates
    - JWT-based authentication with RBAC

    The server integrates with TagManager and ServiceManager using
    the same subscription pattern as the OPC UA server.
    """

    def __init__(
        self,
        config: GatewayConfig,
        tag_manager: TagManager,
        service_manager: ServiceManager | None = None,
    ) -> None:
        """Initialize the WebUI server.

        Args:
            config: Gateway configuration
            tag_manager: Tag manager for value access
            service_manager: Optional ServiceManager for service control
        """
        self._config = config
        self._webui_config = config.webui
        self._tag_manager = tag_manager
        self._service_manager = service_manager

        # Initialize components
        self._token_service = self._create_token_service()
        self._ws_manager = WebSocketManager()
        self._broadcaster: EventBroadcaster | None = None
        self._alarm_detector: AlarmDetector | None = None
        self._history_recorder: HistoryRecorder | None = None
        self._db_pool: DatabasePool | None = None
        self._app: FastAPI | None = None
        self._server: uvicorn.Server | None = None
        self._serve_task: asyncio.Task[None] | None = None
        self._running = False

    def _create_token_service(self) -> TokenService:
        """Create the JWT token service from config."""
        secret = self._webui_config.jwt_secret
        if not secret:
            logger.warning(
                "No JWT secret configured. Using ephemeral secret; tokens will reset on restart."
            )
            secret = secrets.token_urlsafe(32)

        return TokenService(
            secret=secret,
            algorithm=self._webui_config.jwt_algorithm,
            access_expiry_minutes=self._webui_config.jwt_expiry_minutes,
            refresh_expiry_days=self._webui_config.jwt_refresh_expiry_days,
        )

    def _create_app(self) -> FastAPI:
        """Create and configure the FastAPI application."""

        @asynccontextmanager
        async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
            """Manage application lifecycle."""
            # Startup
            logger.info("FastAPI application starting")
            yield
            # Shutdown
            logger.info("FastAPI application shutting down")

        app = FastAPI(
            title="MTP Gateway WebUI",
            description="REST API and WebSocket for MTP Gateway monitoring and control",
            version="1.0.0",
            lifespan=lifespan,
            docs_url="/api/docs" if self._webui_config.enabled else None,
            redoc_url="/api/redoc" if self._webui_config.enabled else None,
            openapi_url="/api/openapi.json" if self._webui_config.enabled else None,
        )

        # Add CORS middleware
        if self._webui_config.cors_origins:
            app.add_middleware(
                CORSMiddleware,
                allow_origins=self._webui_config.cors_origins,
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )

        # Store dependencies for injection
        app.state.tag_manager = self._tag_manager
        app.state.service_manager = self._service_manager
        app.state.token_service = self._token_service
        app.state.ws_manager = self._ws_manager
        app.state.config = self._config

        # Include routers
        self._setup_routers(app)

        return app

    def _setup_routers(self, app: FastAPI) -> None:
        """Setup API routers."""
        # Mount routers with /api/v1 prefix
        app.include_router(health.router, prefix="/api/v1", tags=["health"])
        app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
        app.include_router(tags.router, prefix="/api/v1/tags", tags=["tags"])
        app.include_router(services.router, prefix="/api/v1/services", tags=["services"])
        app.include_router(alarms.router, prefix="/api/v1/alarms", tags=["alarms"])
        app.include_router(history.router, prefix="/api/v1/history", tags=["history"])
        app.include_router(ws.router, prefix="/api/v1", tags=["websocket"])

    async def start(self) -> None:
        """Start the WebUI server."""
        if self._running:
            return

        if not self._webui_config.enabled:
            logger.info("WebUI server disabled in configuration")
            return

        logger.info(
            "Starting WebUI server",
            host=self._webui_config.host,
            port=self._webui_config.port,
        )

        # Initialize database pool if configured
        if self._webui_config.database_url:
            try:
                self._db_pool = DatabasePool(self._webui_config.database_url)
                await self._db_pool.start()
                set_db_pool(self._db_pool)
                logger.info("Database pool initialized")
            except Exception as e:
                logger.warning(
                    "Failed to initialize database pool, running without persistence",
                    error=str(e),
                )
                self._db_pool = None
        else:
            logger.info("No database URL configured, using in-memory storage")

        # Create FastAPI app
        self._app = self._create_app()

        # Store database pool reference for dependency injection
        if self._db_pool:
            self._app.state.db_pool = self._db_pool

        # Create and start broadcaster
        self._broadcaster = EventBroadcaster(
            ws_manager=self._ws_manager,
            min_update_interval_ms=100,
        )
        await self._broadcaster.start()

        # Subscribe to tag changes
        self._tag_manager.subscribe(self._broadcaster.on_tag_change)

        # Subscribe to service state changes
        if self._service_manager:
            self._service_manager.subscribe(self._on_state_change)

        # Start background services
        # HistoryRecorder: records tag values to TimescaleDB
        self._history_recorder = HistoryRecorder(
            tag_manager=self._tag_manager,
            db_pool=self._db_pool,
            config=HistoryConfig(
                flush_interval=1.0,  # Flush every second
                max_buffer_size=100,
            ),
        )
        await self._history_recorder.start()

        # AlarmDetector: monitors AnaMon/BinMon values and raises/clears alarms
        self._alarm_detector = AlarmDetector(
            config=self._config,
            tag_manager=self._tag_manager,
            db_pool=self._db_pool,
            broadcaster=self._broadcaster,
        )
        await self._alarm_detector.start()

        logger.info(
            "Background services started",
            history_recorder=self._history_recorder.is_running,
            alarm_detector=self._alarm_detector.is_running,
            monitors=self._alarm_detector.monitor_count,
        )

        # Create uvicorn server
        uvicorn_config = uvicorn.Config(
            app=self._app,
            host=self._webui_config.host,
            port=self._webui_config.port,
            log_level="warning",
            access_log=False,
        )
        self._server = uvicorn.Server(uvicorn_config)

        # Start serving in background
        self._serve_task = asyncio.create_task(self._server.serve())
        self._running = True

        logger.info(
            "WebUI server started",
            host=self._webui_config.host,
            port=self._webui_config.port,
            docs_url=f"http://{self._webui_config.host}:{self._webui_config.port}/api/docs",
        )

    async def stop(self) -> None:
        """Stop the WebUI server."""
        if not self._running:
            return

        logger.info("Stopping WebUI server")

        # Unsubscribe from managers
        if self._broadcaster:
            self._tag_manager.unsubscribe(self._broadcaster.on_tag_change)

        if self._service_manager:
            self._service_manager.unsubscribe(self._on_state_change)

        # Stop background services (before broadcaster and database)
        if self._alarm_detector:
            await self._alarm_detector.stop()
            self._alarm_detector = None

        if self._history_recorder:
            await self._history_recorder.stop()
            self._history_recorder = None

        # Stop broadcaster
        if self._broadcaster:
            await self._broadcaster.stop()
            self._broadcaster = None

        # Close database pool
        if self._db_pool:
            await self._db_pool.stop()
            set_db_pool(None)
            self._db_pool = None
            logger.info("Database pool closed")

        # Stop uvicorn
        if self._server:
            self._server.should_exit = True

        if self._serve_task:
            try:
                await asyncio.wait_for(self._serve_task, timeout=5.0)
            except TimeoutError:
                self._serve_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._serve_task

        self._server = None
        self._serve_task = None
        self._running = False

        logger.info("WebUI server stopped")

    def _on_state_change(
        self,
        service_name: str,
        from_state: PackMLState,
        to_state: PackMLState,
    ) -> None:
        """Handle service state changes from ServiceManager.

        Args:
            service_name: Name of the service
            from_state: Previous PackML state
            to_state: New PackML state
        """
        if self._broadcaster:
            self._broadcaster.on_state_change(service_name, from_state, to_state)

    @property
    def is_running(self) -> bool:
        """Check if server is running."""
        return self._running

    @property
    def host(self) -> str:
        """Get server host."""
        return self._webui_config.host

    @property
    def port(self) -> int:
        """Get server port."""
        return self._webui_config.port

    @property
    def app(self) -> FastAPI | None:
        """Get the FastAPI application instance."""
        return self._app

    @property
    def ws_manager(self) -> WebSocketManager:
        """Get the WebSocket manager."""
        return self._ws_manager

    @property
    def token_service(self) -> TokenService:
        """Get the token service."""
        return self._token_service
