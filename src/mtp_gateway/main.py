"""Main entry point for MTP Gateway runtime."""

from __future__ import annotations

import asyncio
import signal
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from mtp_gateway.adapters.northbound.opcua.server import MTPOPCUAServer
    from mtp_gateway.adapters.southbound.base import ConnectorPort
    from mtp_gateway.application.service_manager import ServiceManager
    from mtp_gateway.application.tag_manager import TagManager
    from mtp_gateway.config.schema import GatewayConfig

logger = structlog.get_logger(__name__)


class GatewayRuntime:
    """Main runtime orchestrator for the MTP Gateway.

    Coordinates the lifecycle of:
    - Southbound connectors (PLC communication)
    - Tag manager (polling and updates)
    - Service manager (state machine execution)
    - OPC UA server (northbound interface)
    """

    def __init__(self, config: GatewayConfig) -> None:
        self.config = config
        self._shutdown_event = asyncio.Event()
        self._connectors: dict[str, ConnectorPort] = {}
        self._tag_manager: TagManager | None = None
        self._service_manager: ServiceManager | None = None
        self._opcua_server: MTPOPCUAServer | None = None

    async def start(self) -> None:
        """Start the gateway runtime."""
        logger.info(
            "Starting MTP Gateway",
            name=self.config.gateway.name,
            version=self.config.gateway.version,
        )

        # Initialize components in order
        await self._init_connectors()
        await self._init_tag_manager()
        await self._init_service_manager()
        await self._init_opcua_server()

        logger.info("MTP Gateway started successfully")

    async def _init_connectors(self) -> None:
        """Initialize southbound connectors."""
        from mtp_gateway.adapters.southbound.base import create_connector

        for conn_config in self.config.connectors:
            logger.info("Initializing connector", name=conn_config.name, type=conn_config.type)
            connector = create_connector(conn_config)
            await connector.connect()
            self._connectors[conn_config.name] = connector

    async def _init_tag_manager(self) -> None:
        """Initialize tag manager for polling."""
        from mtp_gateway.application.tag_manager import TagManager

        self._tag_manager = TagManager(
            connectors=self._connectors,
            tags=self.config.tags,
        )
        await self._tag_manager.start()

    async def _init_service_manager(self) -> None:
        """Initialize service manager for state machine execution."""
        from mtp_gateway.application.service_manager import ServiceManager

        self._service_manager = ServiceManager(
            tag_manager=self._tag_manager,
            services=self.config.mtp.services,
        )
        await self._service_manager.start()

    async def _init_opcua_server(self) -> None:
        """Initialize OPC UA server."""
        from mtp_gateway.adapters.northbound.opcua.server import MTPOPCUAServer

        self._opcua_server = MTPOPCUAServer(
            config=self.config,
            tag_manager=self._tag_manager,
            service_manager=self._service_manager,
        )
        await self._opcua_server.start()

    async def stop(self) -> None:
        """Stop the gateway runtime gracefully."""
        logger.info("Stopping MTP Gateway")

        # Stop in reverse order
        if self._opcua_server:
            await self._opcua_server.stop()

        if self._service_manager:
            await self._service_manager.stop()

        if self._tag_manager:
            await self._tag_manager.stop()

        for name, connector in self._connectors.items():
            logger.info("Disconnecting connector", name=name)
            await connector.disconnect()

        logger.info("MTP Gateway stopped")

    async def run_until_shutdown(self) -> None:
        """Run until shutdown signal received."""
        await self._shutdown_event.wait()

    def request_shutdown(self) -> None:
        """Request graceful shutdown."""
        self._shutdown_event.set()


async def run_gateway(config_path: Path) -> None:
    """Main entry point for running the gateway."""
    from mtp_gateway.config.loader import load_config
    from mtp_gateway.observability.logging import setup_logging

    # Setup logging first
    setup_logging()

    # Load configuration
    config = load_config(config_path)

    # Create and start runtime
    runtime = GatewayRuntime(config)

    # Setup signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, runtime.request_shutdown)

    try:
        await runtime.start()
        await runtime.run_until_shutdown()
    finally:
        await runtime.stop()


def main() -> None:
    """CLI entry point - delegates to typer app."""
    from mtp_gateway.cli.app import app

    app()


if __name__ == "__main__":
    main()
