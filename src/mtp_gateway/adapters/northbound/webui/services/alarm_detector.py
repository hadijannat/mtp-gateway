"""Alarm detection service for AnaMon/BinMon data assemblies.

Monitors tag values and raises/clears alarms when limits are exceeded.
Integrates with TagManager subscriptions and broadcasts to WebSocket.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from mtp_gateway.adapters.northbound.webui.database.connection import DatabasePool
    from mtp_gateway.adapters.northbound.webui.websocket.broadcaster import EventBroadcaster
    from mtp_gateway.application.tag_manager import TagManager
    from mtp_gateway.config.schema import DataAssemblyConfig, GatewayConfig
    from mtp_gateway.domain.model.tags import TagValue

logger = structlog.get_logger(__name__)


@dataclass
class AlarmState:
    """Tracks alarm state for a single data assembly."""

    alarm_hh: bool = False
    alarm_h: bool = False
    alarm_l: bool = False
    alarm_ll: bool = False
    state_err: bool = False


@dataclass
class MonitorConfig:
    """Configuration for a monitored data assembly."""

    name: str
    tag_name: str
    assembly_type: str  # "AnaMon" or "BinMon"

    # AnaMon limits
    h_limit: float | None = None
    hh_limit: float | None = None
    l_limit: float | None = None
    ll_limit: float | None = None

    # BinMon expected state
    expected_state: bool | None = None

    # Current alarm states
    state: AlarmState = field(default_factory=AlarmState)


class AlarmDetector:
    """Service that detects alarm conditions from monitored values.

    Subscribes to TagManager and monitors AnaMon/BinMon data assemblies.
    When values exceed configured limits, alarms are raised. When values
    return to normal, alarms are automatically cleared.

    Alarm priorities (ISA-18.2):
    - HH/LL: Priority 1 (Critical)
    - H/L: Priority 2 (High)
    - State Error: Priority 2 (High)

    Example:
        detector = AlarmDetector(config, tag_manager, db_pool, broadcaster)
        await detector.start()
        # ... detector now monitors values and raises alarms
        await detector.stop()
    """

    def __init__(
        self,
        config: "GatewayConfig",
        tag_manager: "TagManager",
        db_pool: "DatabasePool | None" = None,
        broadcaster: "EventBroadcaster | None" = None,
    ) -> None:
        """Initialize the alarm detector.

        Args:
            config: Gateway configuration with data assembly definitions
            tag_manager: Tag manager to subscribe to
            db_pool: Optional database pool for persistence
            broadcaster: Optional WebSocket broadcaster for real-time updates
        """
        self._config = config
        self._tag_manager = tag_manager
        self._db_pool = db_pool
        self._broadcaster = broadcaster

        # Monitored assemblies indexed by tag name
        self._monitors: dict[str, MonitorConfig] = {}

        # Running state
        self._running = False
        self._check_task: asyncio.Task | None = None

    def _load_monitors(self) -> None:
        """Load monitor configurations from gateway config."""
        self._monitors.clear()

        for da_config in self._config.mtp.data_assemblies:
            if da_config.type == "AnaMon":
                self._add_ana_mon(da_config)
            elif da_config.type == "BinMon":
                self._add_bin_mon(da_config)

        logger.info(
            "Loaded monitors for alarm detection",
            count=len(self._monitors),
        )

    def _add_ana_mon(self, da_config: "DataAssemblyConfig") -> None:
        """Add an analog monitor to detection."""
        # Get tag name from bindings
        tag_name = da_config.bindings.get("V")
        if not tag_name:
            logger.warning(
                "AnaMon has no V binding",
                name=da_config.name,
            )
            return

        # Get limits from monitor_limits config or defaults
        limits = da_config.monitor_limits
        monitor = MonitorConfig(
            name=da_config.name,
            tag_name=tag_name,
            assembly_type="AnaMon",
            h_limit=limits.h_limit if limits else 90.0,
            hh_limit=limits.hh_limit if limits else 95.0,
            l_limit=limits.l_limit if limits else 10.0,
            ll_limit=limits.ll_limit if limits else 5.0,
        )

        self._monitors[tag_name] = monitor
        logger.debug(
            "Added AnaMon",
            name=da_config.name,
            tag=tag_name,
            limits=(monitor.ll_limit, monitor.l_limit, monitor.h_limit, monitor.hh_limit),
        )

    def _add_bin_mon(self, da_config: "DataAssemblyConfig") -> None:
        """Add a binary monitor to detection."""
        tag_name = da_config.bindings.get("V")
        if not tag_name:
            logger.warning(
                "BinMon has no V binding",
                name=da_config.name,
            )
            return

        # BinMon doesn't have limits in standard config, but could be extended
        monitor = MonitorConfig(
            name=da_config.name,
            tag_name=tag_name,
            assembly_type="BinMon",
            expected_state=None,  # Can be configured if needed
        )

        self._monitors[tag_name] = monitor
        logger.debug(
            "Added BinMon",
            name=da_config.name,
            tag=tag_name,
        )

    async def start(self) -> None:
        """Start the alarm detector service."""
        if self._running:
            return

        # Load monitor configurations
        self._load_monitors()

        if not self._monitors:
            logger.info("No monitors configured, alarm detector disabled")
            return

        # Subscribe to tag changes
        self._tag_manager.subscribe(self._on_tag_change)

        # Start periodic check for shelve expiry
        self._check_task = asyncio.create_task(self._periodic_check())

        self._running = True
        logger.info("Alarm detector started")

    async def stop(self) -> None:
        """Stop the alarm detector service."""
        if not self._running:
            return

        # Unsubscribe from tag changes
        self._tag_manager.unsubscribe(self._on_tag_change)

        # Cancel periodic check
        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
            self._check_task = None

        self._running = False
        logger.info("Alarm detector stopped")

    def _on_tag_change(self, tag_name: str, value: "TagValue") -> None:
        """Handle tag value changes from TagManager.

        This is called synchronously by TagManager, so we schedule
        async alarm processing.

        Args:
            tag_name: Changed tag name
            value: New tag value
        """
        monitor = self._monitors.get(tag_name)
        if not monitor:
            return

        # Schedule async processing
        asyncio.create_task(self._process_value_change(monitor, value))

    async def _process_value_change(
        self,
        monitor: MonitorConfig,
        value: "TagValue",
    ) -> None:
        """Process a tag value change and update alarm states.

        Args:
            monitor: Monitor configuration
            value: New tag value
        """
        if monitor.assembly_type == "AnaMon":
            await self._check_ana_mon_alarms(monitor, value)
        elif monitor.assembly_type == "BinMon":
            await self._check_bin_mon_state(monitor, value)

    async def _check_ana_mon_alarms(
        self,
        monitor: MonitorConfig,
        value: "TagValue",
    ) -> None:
        """Check analog monitor alarm conditions.

        Args:
            monitor: AnaMon configuration
            value: New tag value
        """
        if value.value is None:
            return

        v = float(value.value)
        old_state = AlarmState(
            alarm_hh=monitor.state.alarm_hh,
            alarm_h=monitor.state.alarm_h,
            alarm_l=monitor.state.alarm_l,
            alarm_ll=monitor.state.alarm_ll,
        )

        # Update alarm states based on limits
        monitor.state.alarm_hh = v >= (monitor.hh_limit or 95.0)
        monitor.state.alarm_h = v >= (monitor.h_limit or 90.0)
        monitor.state.alarm_ll = v <= (monitor.ll_limit or 5.0)
        monitor.state.alarm_l = v <= (monitor.l_limit or 10.0)

        # Check for state changes and raise/clear alarms
        await self._handle_alarm_change(
            monitor,
            "HH",
            old_state.alarm_hh,
            monitor.state.alarm_hh,
            v,
            priority=1,
            message=f"{monitor.name} High-High alarm",
        )
        await self._handle_alarm_change(
            monitor,
            "H",
            old_state.alarm_h,
            monitor.state.alarm_h,
            v,
            priority=2,
            message=f"{monitor.name} High alarm",
        )
        await self._handle_alarm_change(
            monitor,
            "L",
            old_state.alarm_l,
            monitor.state.alarm_l,
            v,
            priority=2,
            message=f"{monitor.name} Low alarm",
        )
        await self._handle_alarm_change(
            monitor,
            "LL",
            old_state.alarm_ll,
            monitor.state.alarm_ll,
            v,
            priority=1,
            message=f"{monitor.name} Low-Low alarm",
        )

    async def _check_bin_mon_state(
        self,
        monitor: MonitorConfig,
        value: "TagValue",
    ) -> None:
        """Check binary monitor state error condition.

        Args:
            monitor: BinMon configuration
            value: New tag value
        """
        if monitor.expected_state is None:
            return

        v = bool(value.value)
        old_err = monitor.state.state_err
        monitor.state.state_err = v != monitor.expected_state

        await self._handle_alarm_change(
            monitor,
            "STATE_ERR",
            old_err,
            monitor.state.state_err,
            1.0 if v else 0.0,
            priority=2,
            message=f"{monitor.name} state error",
        )

    async def _handle_alarm_change(
        self,
        monitor: MonitorConfig,
        alarm_type: str,
        old_active: bool,
        new_active: bool,
        value: float,
        priority: int,
        message: str,
    ) -> None:
        """Handle alarm state change - raise or clear alarm.

        Args:
            monitor: Monitor configuration
            alarm_type: Alarm type (HH, H, L, LL, STATE_ERR)
            old_active: Previous alarm state
            new_active: New alarm state
            value: Current value
            priority: Alarm priority (1-4)
            message: Alarm message
        """
        if old_active == new_active:
            return

        alarm_id = f"{monitor.name}_{alarm_type}"
        source = monitor.name

        if new_active:
            # Raise alarm
            await self._raise_alarm(
                alarm_id=alarm_id,
                source=source,
                priority=priority,
                message=message,
                value=value,
            )
        else:
            # Clear alarm
            await self._clear_alarm(alarm_id=alarm_id, source=source)

    async def _raise_alarm(
        self,
        alarm_id: str,
        source: str,
        priority: int,
        message: str,
        value: float,
    ) -> None:
        """Raise a new alarm.

        Args:
            alarm_id: Alarm identifier
            source: Alarm source
            priority: Priority (1-4)
            message: Alarm message
            value: Triggering value
        """
        from mtp_gateway.adapters.northbound.webui.routers.alarms import raise_alarm

        # Get repository if database configured
        alarm_repo = None
        if self._db_pool and self._db_pool.is_connected:
            from mtp_gateway.adapters.northbound.webui.database.repository import (
                AlarmRepository,
            )
            alarm_repo = AlarmRepository(self._db_pool.pool)

        db_id = await raise_alarm(
            alarm_repo=alarm_repo,
            alarm_id=alarm_id,
            source=source,
            priority=priority,
            message=message,
            value=value,
        )

        logger.info(
            "Alarm raised",
            alarm_id=alarm_id,
            source=source,
            priority=priority,
            value=value,
            db_id=db_id,
        )

        # Broadcast to WebSocket clients
        if self._broadcaster:
            self._broadcaster.on_alarm_change(
                action="raised",
                alarm_id=alarm_id,
                source=source,
                priority=priority,
                message=message,
            )

    async def _clear_alarm(self, alarm_id: str, source: str) -> None:
        """Clear an alarm (condition no longer present).

        Args:
            alarm_id: Alarm identifier
            source: Alarm source
        """
        from mtp_gateway.adapters.northbound.webui.routers.alarms import auto_clear_alarm

        alarm_repo = None
        if self._db_pool and self._db_pool.is_connected:
            from mtp_gateway.adapters.northbound.webui.database.repository import (
                AlarmRepository,
            )
            alarm_repo = AlarmRepository(self._db_pool.pool)

        cleared = await auto_clear_alarm(
            alarm_repo=alarm_repo,
            alarm_id=alarm_id,
            source=source,
        )

        if cleared:
            logger.info(
                "Alarm auto-cleared",
                alarm_id=alarm_id,
                source=source,
            )

            # Broadcast to WebSocket clients
            if self._broadcaster:
                self._broadcaster.on_alarm_change(
                    action="cleared",
                    alarm_id=alarm_id,
                    source=source,
                )

    async def _periodic_check(self) -> None:
        """Periodically check for shelve expiry and other maintenance."""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute

                if self._db_pool and self._db_pool.is_connected:
                    from mtp_gateway.adapters.northbound.webui.database.repository import (
                        AlarmRepository,
                    )
                    repo = AlarmRepository(self._db_pool.pool)
                    count = await repo.unshelve_expired()
                    if count > 0:
                        logger.info("Unshelved expired alarms", count=count)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in periodic alarm check", error=str(e))

    @property
    def is_running(self) -> bool:
        """Check if detector is running."""
        return self._running

    @property
    def monitor_count(self) -> int:
        """Get number of monitored assemblies."""
        return len(self._monitors)
