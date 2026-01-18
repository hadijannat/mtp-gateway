"""Main entry point for MTP Gateway runtime."""

from __future__ import annotations

import asyncio
import signal
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from mtp_gateway.adapters.northbound.opcua.server import MTPOPCUAServer
from mtp_gateway.adapters.southbound.base import ConnectorPort, ConnectorState, create_connector
from mtp_gateway.application.service_manager import ServiceManager
from mtp_gateway.application.tag_manager import TagManager
from mtp_gateway.config.loader import load_config
from mtp_gateway.config.schema import CommLossAction
from mtp_gateway.domain.rules.interlocks import (
    ComparisonOperator,
    InterlockBinding,
    InterlockEvaluator,
)
from mtp_gateway.domain.rules.safety import SafetyController
from mtp_gateway.observability.logging import setup_logging

if TYPE_CHECKING:
    from pathlib import Path

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
        self._comm_monitor_task: asyncio.Task[None] | None = None
        self._comm_loss_triggered: set[str] = set()

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
        self._comm_monitor_task = asyncio.create_task(self._comm_monitor_loop())

        logger.info("MTP Gateway started successfully")

    async def _init_connectors(self) -> None:
        """Initialize southbound connectors."""
        for conn_config in self.config.connectors:
            logger.info("Initializing connector", name=conn_config.name, type=conn_config.type)
            connector = create_connector(conn_config)
            await connector.connect()
            self._connectors[conn_config.name] = connector

    async def _init_tag_manager(self) -> None:
        """Initialize tag manager for polling."""
        safety = SafetyController.from_config(self.config.safety)
        self._tag_manager = TagManager(
            connectors=self._connectors,
            tags=self.config.tags,
            safety=safety,
        )
        await self._tag_manager.start()

    async def _init_service_manager(self) -> None:
        """Initialize service manager for state machine execution."""
        interlock_evaluator = self._build_interlock_evaluator()
        safety = SafetyController.from_config(self.config.safety)
        if self._tag_manager is None:
            raise RuntimeError("Tag manager must be initialized before service manager")
        self._service_manager = ServiceManager(
            tag_manager=self._tag_manager,
            services=self.config.mtp.services,
            safety=safety,
            interlock_evaluator=interlock_evaluator,
        )
        await self._service_manager.start()

    async def _init_opcua_server(self) -> None:
        """Initialize OPC UA server."""
        if self._tag_manager is None:
            raise RuntimeError("Tag manager must be initialized before OPC UA server")

        self._opcua_server = MTPOPCUAServer(
            config=self.config,
            tag_manager=self._tag_manager,
            service_manager=self._service_manager,
        )
        await self._opcua_server.start()

    def _build_interlock_evaluator(self) -> InterlockEvaluator | None:
        """Build interlock evaluator from configuration."""
        if not self.config.mtp.data_assemblies:
            return None

        bindings: dict[str, InterlockBinding] = {}
        da_by_name = {da.name: da for da in self.config.mtp.data_assemblies}

        for service in self.config.mtp.services:
            referenced = {p.data_assembly for p in service.parameters}
            referenced.update(service.report_values)

            for da_name in referenced:
                da = da_by_name.get(da_name)
                if not da or not da.interlock_binding:
                    continue

                binding = da.interlock_binding
                element_name = f"{service.name}:{da.name}"
                bindings[element_name] = InterlockBinding(
                    element_name=element_name,
                    source_tag=binding.source_tag,
                    condition=ComparisonOperator(binding.condition.value),
                    ref_value=binding.ref_value,
                )

        if not bindings:
            return None

        return InterlockEvaluator(bindings=bindings)

    async def stop(self) -> None:
        """Stop the gateway runtime gracefully."""
        logger.info("Stopping MTP Gateway")

        if self._comm_monitor_task:
            self._comm_monitor_task.cancel()
            await asyncio.gather(self._comm_monitor_task, return_exceptions=True)
            self._comm_monitor_task = None

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

    async def _comm_monitor_loop(self) -> None:
        """Monitor connector health and trigger configured comm-loss actions."""
        grace_s = self.config.runtime.comm_loss_grace_s
        action = self.config.runtime.comm_loss_action

        while not self._shutdown_event.is_set():
            try:
                now = datetime.now(UTC)
                for name, connector in self._connectors.items():
                    health = connector.health_status()
                    last_success = health.last_success
                    last_error = health.last_error

                    unhealthy = (
                        health.state != ConnectorState.CONNECTED or health.consecutive_errors > 0
                    )
                    elapsed = None
                    if last_success:
                        elapsed = (now - last_success).total_seconds()
                    elif last_error:
                        elapsed = (now - last_error).total_seconds()

                    should_trigger = unhealthy and (elapsed is None or elapsed >= grace_s)
                    if should_trigger and name not in self._comm_loss_triggered:
                        await self._handle_comm_loss(name, action)
                        self._comm_loss_triggered.add(name)
                    elif not unhealthy and name in self._comm_loss_triggered:
                        self._comm_loss_triggered.discard(name)
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Comm monitor error", error=str(e))
                await asyncio.sleep(1.0)

    async def _handle_comm_loss(self, connector_name: str, action: CommLossAction) -> None:
        """Handle communication loss based on configured action."""
        logger.error(
            "Connector communication loss detected",
            connector=connector_name,
            action=action.value,
        )
        if action == CommLossAction.SAFE_STATE:
            if self._tag_manager is None:
                return
            safety = SafetyController.from_config(self.config.safety)
            for tag_name, value in safety.get_safe_state_values().items():
                await self._tag_manager.write_tag(tag_name, value)
        elif action == CommLossAction.ABORT_SERVICES:
            if self._service_manager is None:
                return
            await self._service_manager.emergency_stop()


async def run_gateway(config_path: Path, override_path: Path | None = None) -> None:
    """Main entry point for running the gateway."""
    # Setup logging first
    setup_logging()

    # Load configuration
    config = load_config(config_path, override_path=override_path)

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
    from mtp_gateway.cli.app import app  # noqa: PLC0415

    app()


if __name__ == "__main__":
    main()
