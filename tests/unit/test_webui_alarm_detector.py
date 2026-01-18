"""Tests for WebUI AlarmDetector service.

Tests for:
- Monitor configuration loading from gateway config
- Alarm detection for AnaMon (HH, H, L, LL limits)
- Alarm state tracking and change detection
- Integration with broadcaster for WebSocket updates
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mtp_gateway.adapters.northbound.webui.services.alarm_detector import (
    AlarmDetector,
    AlarmState,
    MonitorConfig,
)


class TestAlarmState:
    """Tests for AlarmState dataclass."""

    def test_default_state_all_false(self) -> None:
        """Should initialize all alarm flags to False."""
        state = AlarmState()

        assert state.alarm_hh is False
        assert state.alarm_h is False
        assert state.alarm_l is False
        assert state.alarm_ll is False
        assert state.state_err is False

    def test_can_set_individual_alarms(self) -> None:
        """Should allow setting individual alarm flags."""
        state = AlarmState()
        state.alarm_hh = True
        state.alarm_l = True

        assert state.alarm_hh is True
        assert state.alarm_h is False
        assert state.alarm_l is True
        assert state.alarm_ll is False


class TestMonitorConfig:
    """Tests for MonitorConfig dataclass."""

    def test_ana_mon_config(self) -> None:
        """Should store AnaMon configuration."""
        config = MonitorConfig(
            name="temp_monitor",
            tag_name="TIC_001_V",
            assembly_type="AnaMon",
            h_limit=80.0,
            hh_limit=90.0,
            l_limit=20.0,
            ll_limit=10.0,
        )

        assert config.name == "temp_monitor"
        assert config.tag_name == "TIC_001_V"
        assert config.assembly_type == "AnaMon"
        assert config.h_limit == 80.0
        assert config.hh_limit == 90.0
        assert config.l_limit == 20.0
        assert config.ll_limit == 10.0
        assert config.expected_state is None

    def test_bin_mon_config(self) -> None:
        """Should store BinMon configuration."""
        config = MonitorConfig(
            name="switch_monitor",
            tag_name="HS_001_V",
            assembly_type="BinMon",
            expected_state=True,
        )

        assert config.name == "switch_monitor"
        assert config.tag_name == "HS_001_V"
        assert config.assembly_type == "BinMon"
        assert config.expected_state is True
        assert config.h_limit is None

    def test_has_default_alarm_state(self) -> None:
        """Should initialize with default AlarmState."""
        config = MonitorConfig(
            name="test",
            tag_name="tag",
            assembly_type="AnaMon",
        )

        assert config.state.alarm_hh is False
        assert config.state.alarm_h is False


class TestAlarmDetector:
    """Tests for AlarmDetector service."""

    @pytest.fixture
    def mock_tag_manager(self) -> MagicMock:
        """Create a mock TagManager."""
        tag_manager = MagicMock()
        tag_manager.subscribe = MagicMock()
        tag_manager.unsubscribe = MagicMock()
        return tag_manager

    @pytest.fixture
    def mock_gateway_config(self) -> MagicMock:
        """Create a mock GatewayConfig with data assemblies."""
        config = MagicMock()
        config.mtp.data_assemblies = []
        return config

    @pytest.fixture
    def detector(
        self, mock_gateway_config: MagicMock, mock_tag_manager: MagicMock
    ) -> AlarmDetector:
        """Create an AlarmDetector instance."""
        return AlarmDetector(
            config=mock_gateway_config,
            tag_manager=mock_tag_manager,
            db_pool=None,
            broadcaster=None,
        )

    def test_init_no_monitors(
        self, mock_gateway_config: MagicMock, mock_tag_manager: MagicMock
    ) -> None:
        """Should initialize with empty monitors when no data assemblies."""
        detector = AlarmDetector(
            config=mock_gateway_config,
            tag_manager=mock_tag_manager,
        )

        assert detector.monitor_count == 0
        assert not detector.is_running

    @pytest.mark.asyncio
    async def test_start_with_no_monitors_disables(
        self, detector: AlarmDetector, mock_tag_manager: MagicMock
    ) -> None:
        """Should not start if no monitors configured."""
        await detector.start()

        # Should not subscribe to tag manager
        mock_tag_manager.subscribe.assert_not_called()
        assert not detector.is_running

    @pytest.mark.asyncio
    async def test_start_subscribes_to_tag_manager(
        self,
        mock_gateway_config: MagicMock,
        mock_tag_manager: MagicMock,
    ) -> None:
        """Should subscribe to tag changes when monitors configured."""
        # Add a mock AnaMon assembly
        mock_assembly = MagicMock()
        mock_assembly.type = "AnaMon"
        mock_assembly.name = "temp_monitor"
        mock_assembly.bindings = {"V": "TIC_001_V"}
        mock_assembly.monitor_limits = MagicMock()
        mock_assembly.monitor_limits.h_limit = 80.0
        mock_assembly.monitor_limits.hh_limit = 90.0
        mock_assembly.monitor_limits.l_limit = 20.0
        mock_assembly.monitor_limits.ll_limit = 10.0

        mock_gateway_config.mtp.data_assemblies = [mock_assembly]

        detector = AlarmDetector(
            config=mock_gateway_config,
            tag_manager=mock_tag_manager,
        )

        await detector.start()
        try:
            mock_tag_manager.subscribe.assert_called_once()
            assert detector.is_running
            assert detector.monitor_count == 1
        finally:
            await detector.stop()

    @pytest.mark.asyncio
    async def test_start_is_idempotent(
        self,
        mock_gateway_config: MagicMock,
        mock_tag_manager: MagicMock,
    ) -> None:
        """Should not subscribe twice."""
        # Add a mock assembly so _load_monitors creates a monitor
        mock_assembly = MagicMock()
        mock_assembly.type = "AnaMon"
        mock_assembly.name = "test_monitor"
        mock_assembly.bindings = {"V": "test_tag"}
        mock_assembly.monitor_limits = None
        mock_gateway_config.mtp.data_assemblies = [mock_assembly]

        detector = AlarmDetector(
            config=mock_gateway_config,
            tag_manager=mock_tag_manager,
        )

        await detector.start()
        try:
            await detector.start()  # Second call should be no-op
            assert mock_tag_manager.subscribe.call_count == 1
        finally:
            await detector.stop()

    @pytest.mark.asyncio
    async def test_stop_unsubscribes(
        self,
        mock_gateway_config: MagicMock,
        mock_tag_manager: MagicMock,
    ) -> None:
        """Should unsubscribe on stop."""
        mock_assembly = MagicMock()
        mock_assembly.type = "AnaMon"
        mock_assembly.name = "test_monitor"
        mock_assembly.bindings = {"V": "test_tag"}
        mock_assembly.monitor_limits = None
        mock_gateway_config.mtp.data_assemblies = [mock_assembly]

        detector = AlarmDetector(
            config=mock_gateway_config,
            tag_manager=mock_tag_manager,
        )

        await detector.start()
        await detector.stop()

        mock_tag_manager.unsubscribe.assert_called_once()
        assert not detector.is_running

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(
        self,
        mock_gateway_config: MagicMock,
        mock_tag_manager: MagicMock,
    ) -> None:
        """Should handle multiple stop calls."""
        mock_assembly = MagicMock()
        mock_assembly.type = "AnaMon"
        mock_assembly.name = "test_monitor"
        mock_assembly.bindings = {"V": "test_tag"}
        mock_assembly.monitor_limits = None
        mock_gateway_config.mtp.data_assemblies = [mock_assembly]

        detector = AlarmDetector(
            config=mock_gateway_config,
            tag_manager=mock_tag_manager,
        )

        await detector.start()
        await detector.stop()
        await detector.stop()  # Second call should be no-op

        assert mock_tag_manager.unsubscribe.call_count == 1


class TestAlarmDetectorAnalogMonitor:
    """Tests for AlarmDetector analog monitoring logic."""

    @pytest.fixture
    def mock_tag_manager(self) -> MagicMock:
        """Create a mock TagManager."""
        tag_manager = MagicMock()
        tag_manager.subscribe = MagicMock()
        tag_manager.unsubscribe = MagicMock()
        return tag_manager

    @pytest.fixture
    def mock_gateway_config(self) -> MagicMock:
        """Create a mock GatewayConfig."""
        config = MagicMock()
        config.mtp.data_assemblies = []
        return config

    @pytest.fixture
    def monitor(self) -> MonitorConfig:
        """Create a monitor config for testing."""
        return MonitorConfig(
            name="temp_monitor",
            tag_name="TIC_001_V",
            assembly_type="AnaMon",
            h_limit=80.0,
            hh_limit=90.0,
            l_limit=20.0,
            ll_limit=10.0,
        )

    @pytest.fixture
    def detector_with_monitor(
        self,
        mock_gateway_config: MagicMock,
        mock_tag_manager: MagicMock,
        monitor: MonitorConfig,
    ) -> AlarmDetector:
        """Create a detector with a pre-configured monitor."""
        detector = AlarmDetector(
            config=mock_gateway_config,
            tag_manager=mock_tag_manager,
        )
        detector._monitors[monitor.tag_name] = monitor
        return detector

    @pytest.mark.asyncio
    async def test_value_in_normal_range_no_alarm(
        self, detector_with_monitor: AlarmDetector, monitor: MonitorConfig
    ) -> None:
        """Should not raise alarms when value is in normal range."""
        mock_value = MagicMock()
        mock_value.value = 50.0  # Normal value

        # Patch the alarm raising function (local import - patch at source)
        with patch(
            "mtp_gateway.adapters.northbound.webui.routers.alarms.raise_alarm",
            new_callable=AsyncMock,
        ):
            await detector_with_monitor._check_ana_mon_alarms(monitor, mock_value)

            assert not monitor.state.alarm_hh
            assert not monitor.state.alarm_h
            assert not monitor.state.alarm_l
            assert not monitor.state.alarm_ll

    @pytest.mark.asyncio
    async def test_high_value_triggers_h_alarm(
        self, detector_with_monitor: AlarmDetector, monitor: MonitorConfig
    ) -> None:
        """Should raise H alarm when value exceeds high limit."""
        mock_value = MagicMock()
        mock_value.value = 85.0  # Above H (80) but below HH (90)

        with patch(
            "mtp_gateway.adapters.northbound.webui.routers.alarms.raise_alarm",
            new_callable=AsyncMock,
        ) as mock_raise:
            await detector_with_monitor._check_ana_mon_alarms(monitor, mock_value)

            # H alarm should be raised
            mock_raise.assert_called()
            assert monitor.state.alarm_h is True
            assert monitor.state.alarm_hh is False  # Not yet HH

    @pytest.mark.asyncio
    async def test_very_high_value_triggers_hh_alarm(
        self, detector_with_monitor: AlarmDetector, monitor: MonitorConfig
    ) -> None:
        """Should raise HH alarm when value exceeds high-high limit."""
        mock_value = MagicMock()
        mock_value.value = 95.0  # Above HH (90)

        with patch(
            "mtp_gateway.adapters.northbound.webui.routers.alarms.raise_alarm",
            new_callable=AsyncMock,
        ):
            await detector_with_monitor._check_ana_mon_alarms(monitor, mock_value)

            # Both H and HH alarms should be raised
            assert monitor.state.alarm_h is True
            assert monitor.state.alarm_hh is True

    @pytest.mark.asyncio
    async def test_low_value_triggers_l_alarm(
        self, detector_with_monitor: AlarmDetector, monitor: MonitorConfig
    ) -> None:
        """Should raise L alarm when value goes below low limit."""
        mock_value = MagicMock()
        mock_value.value = 15.0  # Below L (20) but above LL (10)

        with patch(
            "mtp_gateway.adapters.northbound.webui.routers.alarms.raise_alarm",
            new_callable=AsyncMock,
        ):
            await detector_with_monitor._check_ana_mon_alarms(monitor, mock_value)

            assert monitor.state.alarm_l is True
            assert monitor.state.alarm_ll is False

    @pytest.mark.asyncio
    async def test_very_low_value_triggers_ll_alarm(
        self, detector_with_monitor: AlarmDetector, monitor: MonitorConfig
    ) -> None:
        """Should raise LL alarm when value goes below low-low limit."""
        mock_value = MagicMock()
        mock_value.value = 5.0  # Below LL (10)

        with patch(
            "mtp_gateway.adapters.northbound.webui.routers.alarms.raise_alarm",
            new_callable=AsyncMock,
        ):
            await detector_with_monitor._check_ana_mon_alarms(monitor, mock_value)

            assert monitor.state.alarm_l is True
            assert monitor.state.alarm_ll is True

    @pytest.mark.asyncio
    async def test_alarm_clears_when_value_returns_to_normal(
        self, detector_with_monitor: AlarmDetector, monitor: MonitorConfig
    ) -> None:
        """Should clear alarm when value returns to normal."""
        # First trigger H alarm
        monitor.state.alarm_h = True

        mock_value = MagicMock()
        mock_value.value = 50.0  # Back to normal

        with (
            patch(
                "mtp_gateway.adapters.northbound.webui.routers.alarms.raise_alarm",
                new_callable=AsyncMock,
            ),
            patch(
                "mtp_gateway.adapters.northbound.webui.routers.alarms.auto_clear_alarm",
                new_callable=AsyncMock,
            ) as mock_clear,
        ):
            await detector_with_monitor._check_ana_mon_alarms(monitor, mock_value)

            # Clear should be called for H alarm
            mock_clear.assert_called()
            assert monitor.state.alarm_h is False

    @pytest.mark.asyncio
    async def test_none_value_is_ignored(
        self, detector_with_monitor: AlarmDetector, monitor: MonitorConfig
    ) -> None:
        """Should skip processing when value is None."""
        mock_value = MagicMock()
        mock_value.value = None

        with patch(
            "mtp_gateway.adapters.northbound.webui.routers.alarms.raise_alarm",
            new_callable=AsyncMock,
        ) as mock_raise:
            await detector_with_monitor._check_ana_mon_alarms(monitor, mock_value)

            mock_raise.assert_not_called()


class TestAlarmDetectorBroadcasting:
    """Tests for AlarmDetector WebSocket broadcasting."""

    @pytest.fixture
    def mock_broadcaster(self) -> MagicMock:
        """Create a mock EventBroadcaster."""
        broadcaster = MagicMock()
        broadcaster.on_alarm_change = MagicMock()
        return broadcaster

    @pytest.fixture
    def mock_tag_manager(self) -> MagicMock:
        """Create a mock TagManager."""
        tag_manager = MagicMock()
        tag_manager.subscribe = MagicMock()
        tag_manager.unsubscribe = MagicMock()
        return tag_manager

    @pytest.fixture
    def mock_gateway_config(self) -> MagicMock:
        """Create a mock GatewayConfig."""
        config = MagicMock()
        config.mtp.data_assemblies = []
        return config

    @pytest.mark.asyncio
    async def test_broadcasts_alarm_raised(
        self,
        mock_gateway_config: MagicMock,
        mock_tag_manager: MagicMock,
        mock_broadcaster: MagicMock,
    ) -> None:
        """Should broadcast when alarm is raised."""
        detector = AlarmDetector(
            config=mock_gateway_config,
            tag_manager=mock_tag_manager,
            broadcaster=mock_broadcaster,
        )

        with patch(
            "mtp_gateway.adapters.northbound.webui.routers.alarms.raise_alarm",
            new_callable=AsyncMock,
            return_value=1,
        ):
            await detector._raise_alarm(
                alarm_id="TIC_001_H",
                source="temp_monitor",
                priority=2,
                message="High temperature alarm",
                value=85.0,
            )

            mock_broadcaster.on_alarm_change.assert_called_once_with(
                action="raised",
                alarm_id="TIC_001_H",
                source="temp_monitor",
                priority=2,
                message="High temperature alarm",
            )

    @pytest.mark.asyncio
    async def test_broadcasts_alarm_cleared(
        self,
        mock_gateway_config: MagicMock,
        mock_tag_manager: MagicMock,
        mock_broadcaster: MagicMock,
    ) -> None:
        """Should broadcast when alarm is cleared."""
        detector = AlarmDetector(
            config=mock_gateway_config,
            tag_manager=mock_tag_manager,
            broadcaster=mock_broadcaster,
        )

        with patch(
            "mtp_gateway.adapters.northbound.webui.routers.alarms.auto_clear_alarm",
            new_callable=AsyncMock,
            return_value=True,
        ):
            await detector._clear_alarm(
                alarm_id="TIC_001_H",
                source="temp_monitor",
            )

            mock_broadcaster.on_alarm_change.assert_called_once_with(
                action="cleared",
                alarm_id="TIC_001_H",
                source="temp_monitor",
            )

    @pytest.mark.asyncio
    async def test_no_broadcast_when_alarm_not_cleared(
        self,
        mock_gateway_config: MagicMock,
        mock_tag_manager: MagicMock,
        mock_broadcaster: MagicMock,
    ) -> None:
        """Should not broadcast if alarm wasn't actually cleared."""
        detector = AlarmDetector(
            config=mock_gateway_config,
            tag_manager=mock_tag_manager,
            broadcaster=mock_broadcaster,
        )

        with patch(
            "mtp_gateway.adapters.northbound.webui.routers.alarms.auto_clear_alarm",
            new_callable=AsyncMock,
            return_value=False,  # Alarm not found/already cleared
        ):
            await detector._clear_alarm(
                alarm_id="TIC_001_H",
                source="temp_monitor",
            )

            mock_broadcaster.on_alarm_change.assert_not_called()
