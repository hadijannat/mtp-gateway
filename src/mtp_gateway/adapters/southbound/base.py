"""Base protocol and utilities for southbound PLC connectors.

Defines the ConnectorPort protocol that all protocol adapters must implement,
plus common utilities for health tracking, backoff, and error handling.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import structlog

from mtp_gateway.config.schema import ConnectorConfig, ConnectorType
from mtp_gateway.domain.model.tags import Quality, TagValue

if TYPE_CHECKING:
    from mtp_gateway.domain.model.tags import TagDefinition

logger = structlog.get_logger(__name__)


class ConnectorState(Enum):
    """Connection state for connectors."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass
class ConnectorHealth:
    """Health status for a connector."""

    state: ConnectorState
    last_success: datetime | None = None
    last_error: datetime | None = None
    last_error_message: str | None = None
    consecutive_errors: int = 0
    total_reads: int = 0
    total_writes: int = 0
    total_errors: int = 0

    @property
    def is_healthy(self) -> bool:
        """Check if connector is in a healthy state."""
        return self.state == ConnectorState.CONNECTED and self.consecutive_errors == 0

    def record_success(self) -> None:
        """Record a successful operation."""
        self.last_success = datetime.now(UTC)
        self.consecutive_errors = 0

    def record_error(self, message: str) -> None:
        """Record a failed operation."""
        self.last_error = datetime.now(UTC)
        self.last_error_message = message
        self.consecutive_errors += 1
        self.total_errors += 1


@runtime_checkable
class ConnectorPort(Protocol):
    """Protocol defining the interface for southbound PLC connectors.

    All protocol adapters (Modbus, S7, EIP, OPC UA) must implement this interface.
    This follows the ports-and-adapters pattern for dependency inversion.
    """

    @property
    def name(self) -> str:
        """Return the connector name from configuration."""
        ...

    async def connect(self) -> None:
        """Establish connection to the PLC.

        Raises:
            ConnectionError: If connection cannot be established
        """
        ...

    async def disconnect(self) -> None:
        """Gracefully close the connection."""
        ...

    async def read_tags(self, addresses: list[str]) -> dict[str, TagValue]:
        """Read multiple tag values from the PLC.

        Args:
            addresses: List of protocol-specific addresses to read

        Returns:
            Dictionary mapping addresses to TagValue instances

        Raises:
            ConnectionError: If communication fails
        """
        ...

    async def read_tag_values(self, tags: list[TagDefinition]) -> dict[str, TagValue]:
        """Read multiple tags with datatype metadata.

        Returns a mapping of tag name to TagValue.
        """
        ...

    async def write_tag(self, address: str, value: Any) -> bool:
        """Write a single value to the PLC.

        Args:
            address: Protocol-specific address
            value: Value to write (type must match tag configuration)

        Returns:
            True if write succeeded, False otherwise

        Raises:
            ConnectionError: If communication fails
            ValueError: If value type is invalid
        """
        ...

    async def write_tag_value(self, tag: TagDefinition, value: Any) -> bool:
        """Write a value to a tag using its definition metadata."""
        ...

    def health_status(self) -> ConnectorHealth:
        """Return current health status."""
        ...


class BaseConnector(ABC):
    """Base class for connector implementations.

    Provides common functionality for health tracking, reconnection,
    and error handling.
    """

    def __init__(self, config: ConnectorConfig) -> None:
        self._config: ConnectorConfig = config
        self._health = ConnectorHealth(state=ConnectorState.DISCONNECTED)
        self._lock = asyncio.Lock()
        self._backoff = ExponentialBackoff(
            base_delay=config.retry_delay_ms / 1000,
            max_delay=30.0,
            max_retries=config.retry_count,
        )

    @property
    def name(self) -> str:
        """Return the connector name."""
        return self._config.name

    def health_status(self) -> ConnectorHealth:
        """Return current health status."""
        return self._health

    @abstractmethod
    async def _do_connect(self) -> None:
        """Implementation-specific connection logic."""
        ...

    @abstractmethod
    async def _do_disconnect(self) -> None:
        """Implementation-specific disconnection logic."""
        ...

    @abstractmethod
    async def _do_read(self, addresses: list[str]) -> dict[str, Any]:
        """Implementation-specific read logic."""
        ...

    @abstractmethod
    async def _do_write(self, address: str, value: Any) -> None:
        """Implementation-specific write logic."""
        ...

    async def connect(self) -> None:
        """Connect with retry logic."""
        async with self._lock:
            if self._health.state == ConnectorState.CONNECTED:
                return

            self._health.state = ConnectorState.CONNECTING
            logger.info("Connecting to PLC", connector=self.name)

            try:
                await self._do_connect()
                self._health.state = ConnectorState.CONNECTED
                self._health.record_success()
                self._backoff.reset()
                logger.info("Connected to PLC", connector=self.name)
            except Exception as e:
                self._health.state = ConnectorState.ERROR
                self._health.record_error(str(e))
                logger.error("Failed to connect", connector=self.name, error=str(e))
                raise ConnectionError(f"Failed to connect: {e}") from e

    async def disconnect(self) -> None:
        """Disconnect gracefully."""
        async with self._lock:
            if self._health.state in (ConnectorState.DISCONNECTED, ConnectorState.STOPPED):
                return

            logger.info("Disconnecting from PLC", connector=self.name)
            try:
                await self._do_disconnect()
            except Exception as e:
                logger.warning("Error during disconnect", connector=self.name, error=str(e))
            finally:
                self._health.state = ConnectorState.STOPPED

    async def read_tags(self, addresses: list[str]) -> dict[str, TagValue]:
        """Read tags with error handling and quality tracking."""
        if not addresses:
            return {}

        self._health.total_reads += len(addresses)

        try:
            raw_values = await self._do_read(addresses)
            self._health.record_success()

            # Convert raw values to TagValue with good quality
            result: dict[str, TagValue] = {}
            now = datetime.now(UTC)
            for addr in addresses:
                if addr in raw_values:
                    result[addr] = TagValue(
                        value=raw_values[addr],
                        timestamp=now,
                        quality=Quality.GOOD,
                    )
                else:
                    result[addr] = TagValue(
                        value=0,
                        timestamp=now,
                        quality=Quality.BAD_CONFIG_ERROR,
                    )
            return result

        except Exception as e:
            self._health.record_error(str(e))
            logger.warning(
                "Read failed",
                connector=self.name,
                addresses=addresses,
                error=str(e),
            )

            # Return bad quality values
            now = datetime.now(UTC)
            return {
                addr: TagValue(
                    value=0,
                    timestamp=now,
                    quality=Quality.BAD_NO_COMMUNICATION,
                )
                for addr in addresses
            }

    async def read_tag_values(self, tags: list[TagDefinition]) -> dict[str, TagValue]:
        """Read tags using their definitions.

        Default implementation maps TagDefinition -> address and delegates
        to read_tags(). Connectors may override for protocol-specific decoding.
        """
        if not tags:
            return {}

        values_by_address = await self.read_tags([tag.address for tag in tags])
        return {
            tag.name: values_by_address.get(tag.address, TagValue.bad_no_comm()) for tag in tags
        }

    async def write_tag(self, address: str, value: Any) -> bool:
        """Write with error handling."""
        self._health.total_writes += 1

        try:
            await self._do_write(address, value)
            self._health.record_success()
            logger.debug("Write successful", connector=self.name, address=address)
            return True
        except Exception as e:
            self._health.record_error(str(e))
            logger.error(
                "Write failed",
                connector=self.name,
                address=address,
                error=str(e),
            )
            return False

    async def write_tag_value(self, tag: TagDefinition, value: Any) -> bool:
        """Write a tag using its definition metadata."""
        return await self.write_tag(tag.address, value)

    async def reconnect(self) -> bool:
        """Attempt reconnection with backoff."""
        async with self._lock:
            self._health.state = ConnectorState.RECONNECTING

            delay = self._backoff.next_delay()
            if delay is None:
                logger.error(
                    "Max reconnection attempts reached",
                    connector=self.name,
                )
                self._health.state = ConnectorState.ERROR
                return False

            logger.info(
                "Reconnecting after delay",
                connector=self.name,
                delay_s=delay,
                attempt=self._backoff.attempts,
            )
            await asyncio.sleep(delay)

            with contextlib.suppress(Exception):
                await self._do_disconnect()

            try:
                await self._do_connect()
                self._health.state = ConnectorState.CONNECTED
                self._health.record_success()
                self._backoff.reset()
                logger.info("Reconnected successfully", connector=self.name)
                return True
            except Exception as e:
                self._health.record_error(str(e))
                logger.warning(
                    "Reconnection failed",
                    connector=self.name,
                    error=str(e),
                )
                return False


@dataclass
class ExponentialBackoff:
    """Exponential backoff with jitter for retry logic."""

    base_delay: float = 1.0
    max_delay: float = 60.0
    max_retries: int = 10
    jitter: float = 0.1
    attempts: int = field(default=0, init=False)

    def next_delay(self) -> float | None:
        """Calculate next delay with exponential backoff and jitter.

        Returns:
            Delay in seconds, or None if max retries exceeded
        """
        if self.attempts >= self.max_retries:
            return None

        self.attempts += 1
        delay = min(self.base_delay * (2 ** (self.attempts - 1)), self.max_delay)

        # Add jitter to prevent thundering herd
        jitter_range = delay * self.jitter
        delay += random.uniform(-jitter_range, jitter_range)

        return max(0.1, float(delay))

    def reset(self) -> None:
        """Reset attempt counter."""
        self.attempts = 0


def create_connector(config: ConnectorConfig) -> ConnectorPort:
    """Factory function to create a connector from configuration.

    Args:
        config: Connector configuration (discriminated union)

    Returns:
        Connector instance implementing ConnectorPort

    Raises:
        ValueError: If connector type is not supported
    """
    # Import implementations here to avoid circular imports
    if config.type == ConnectorType.MODBUS_TCP:
        from mtp_gateway.adapters.southbound.modbus.driver import (  # noqa: PLC0415
            ModbusTCPConnector,
        )

        return ModbusTCPConnector(config)

    elif config.type == ConnectorType.MODBUS_RTU:
        from mtp_gateway.adapters.southbound.modbus.driver import (  # noqa: PLC0415
            ModbusRTUConnector,
        )

        return ModbusRTUConnector(config)

    elif config.type == ConnectorType.S7:
        from mtp_gateway.adapters.southbound.s7.driver import S7Connector  # noqa: PLC0415

        return S7Connector(config)

    elif config.type == ConnectorType.EIP:
        from mtp_gateway.adapters.southbound.eip.driver import EIPConnector  # noqa: PLC0415

        return EIPConnector(config)

    elif config.type == ConnectorType.OPCUA_CLIENT:
        from mtp_gateway.adapters.southbound.opcua_client.driver import (  # noqa: PLC0415
            OPCUAClientConnector,
        )

        return OPCUAClientConnector(config)

    else:
        raise ValueError(f"Unsupported connector type: {config.type}")
