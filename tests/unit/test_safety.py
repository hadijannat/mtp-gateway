"""Unit tests for Safety Controls (Phase 8).

Tests for:
- RateLimiter: Token bucket rate limiting for write operations
- SafetyController: Allowlist validation and safe state outputs
- TagManager safety integration: Blocking writes based on safety rules
- ServiceManager emergency_stop: Setting safe outputs and aborting services
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Will fail initially - these don't exist yet
from mtp_gateway.domain.rules.safety import (
    RateLimiter,
    SafetyController,
    WriteValidation,
    parse_rate_string,
)

from mtp_gateway.application.service_manager import ServiceManager
from mtp_gateway.application.tag_manager import TagManager
from mtp_gateway.config.schema import (
    ProxyMode,
    SafeStateOutput,
    SafetyConfig,
    ServiceConfig,
    TagConfig,
    DataTypeConfig,
)
from mtp_gateway.domain.model.tags import Quality, TagValue
from mtp_gateway.domain.state_machine.packml import PackMLCommand, PackMLState


# =============================================================================
# RateLimiter Tests
# =============================================================================


class TestParseRateString:
    """Tests for parsing rate limit strings."""

    def test_parse_per_second(self) -> None:
        """Should parse '10/s' as 10.0 max per second."""
        rate = parse_rate_string("10/s")
        assert rate == 10.0

    def test_parse_per_minute(self) -> None:
        """Should parse '60/m' as 1.0 per second (60/60)."""
        rate = parse_rate_string("60/m")
        assert rate == 1.0

    def test_parse_per_hour(self) -> None:
        """Should parse '3600/h' as 1.0 per second."""
        rate = parse_rate_string("3600/h")
        assert rate == 1.0

    def test_parse_decimal(self) -> None:
        """Should parse decimal rates like '0.5/s'."""
        rate = parse_rate_string("0.5/s")
        assert rate == 0.5

    def test_invalid_format_raises(self) -> None:
        """Should raise ValueError for invalid format."""
        with pytest.raises(ValueError, match="Invalid rate"):
            parse_rate_string("invalid")

    def test_zero_rate_raises(self) -> None:
        """Should raise ValueError for zero rate."""
        with pytest.raises(ValueError, match="must be positive"):
            parse_rate_string("0/s")

    def test_negative_rate_raises(self) -> None:
        """Should raise ValueError for negative rate."""
        with pytest.raises(ValueError, match="must be positive"):
            parse_rate_string("-5/s")


class TestRateLimiter:
    """Tests for token bucket rate limiter."""

    def test_allows_writes_within_limit(self) -> None:
        """Should allow writes when within rate limit."""
        limiter = RateLimiter(max_per_second=10.0)

        # First write should always succeed
        assert limiter.try_acquire() is True

    def test_blocks_writes_exceeding_limit(self) -> None:
        """Should block writes that exceed the rate limit."""
        limiter = RateLimiter(max_per_second=1.0)

        # First write succeeds
        assert limiter.try_acquire() is True

        # Second immediate write should fail (no time to refill)
        assert limiter.try_acquire() is False

    def test_tokens_refill_over_time(self) -> None:
        """Tokens should refill over time."""
        limiter = RateLimiter(max_per_second=10.0)

        # Exhaust initial token
        assert limiter.try_acquire() is True

        # Wait for partial refill (0.2s = 2 tokens at 10/s)
        time.sleep(0.2)

        # Should have tokens again
        assert limiter.try_acquire() is True

    def test_burst_allowed_up_to_limit(self) -> None:
        """Should allow bursts up to the configured rate."""
        limiter = RateLimiter(max_per_second=5.0)

        # Wait to accumulate full capacity
        time.sleep(0.5)

        # Should allow up to 5 rapid calls (burst capacity = max_per_second)
        success_count = sum(1 for _ in range(5) if limiter.try_acquire())
        assert success_count >= 3  # At least 3 should succeed

    def test_from_rate_string(self) -> None:
        """Should create RateLimiter from rate string."""
        limiter = RateLimiter.from_rate_string("10/s")
        assert limiter.max_per_second == 10.0


# =============================================================================
# SafetyController Tests
# =============================================================================


class TestWriteValidation:
    """Tests for WriteValidation result type."""

    def test_allowed_validation(self) -> None:
        """Should create allowed validation result."""
        validation = WriteValidation(allowed=True)
        assert validation.allowed is True
        assert validation.reason is None

    def test_denied_validation_with_reason(self) -> None:
        """Should create denied validation with reason."""
        validation = WriteValidation(allowed=False, reason="Not in allowlist")
        assert validation.allowed is False
        assert validation.reason == "Not in allowlist"


class TestSafetyController:
    """Tests for SafetyController."""

    def test_write_allowed_in_allowlist(self) -> None:
        """Tags in allowlist should be allowed for writing."""
        controller = SafetyController(
            write_allowlist=frozenset({"Motor.Speed", "Pump.Flow"}),
            safe_state_outputs=(),
            rate_limiter=None,
        )

        validation = controller.validate_write("Motor.Speed")
        assert validation.allowed is True

    def test_write_blocked_not_in_allowlist(self) -> None:
        """Tags not in allowlist should be blocked."""
        controller = SafetyController(
            write_allowlist=frozenset({"Motor.Speed"}),
            safe_state_outputs=(),
            rate_limiter=None,
        )

        validation = controller.validate_write("Sensor.Value")
        assert validation.allowed is False
        assert "allowlist" in validation.reason.lower()

    def test_empty_allowlist_blocks_all_writes(self) -> None:
        """Empty allowlist should block all writes."""
        controller = SafetyController(
            write_allowlist=frozenset(),
            safe_state_outputs=(),
            rate_limiter=None,
        )

        validation = controller.validate_write("Any.Tag")
        assert validation.allowed is False

    def test_safe_state_outputs_returns_configured_values(self) -> None:
        """get_safe_state_values() should return configured safe outputs."""
        controller = SafetyController(
            write_allowlist=frozenset(),
            safe_state_outputs=(
                ("Motor.Speed", 0),
                ("Pump.Enable", False),
                ("Valve.Position", 0.0),
            ),
            rate_limiter=None,
        )

        values = controller.get_safe_state_values()

        assert values == {
            "Motor.Speed": 0,
            "Pump.Enable": False,
            "Valve.Position": 0.0,
        }

    def test_empty_safe_state_outputs(self) -> None:
        """get_safe_state_values() with no outputs returns empty dict."""
        controller = SafetyController(
            write_allowlist=frozenset(),
            safe_state_outputs=(),
            rate_limiter=None,
        )

        values = controller.get_safe_state_values()
        assert values == {}

    def test_rate_limit_check_with_limiter(self) -> None:
        """check_rate_limit() should delegate to RateLimiter."""
        limiter = RateLimiter(max_per_second=1.0)
        controller = SafetyController(
            write_allowlist=frozenset({"Tag1"}),
            safe_state_outputs=(),
            rate_limiter=limiter,
        )

        # First call should pass
        assert controller.check_rate_limit() is True

        # Second immediate call should fail
        assert controller.check_rate_limit() is False

    def test_rate_limit_check_without_limiter(self) -> None:
        """check_rate_limit() without limiter should always return True."""
        controller = SafetyController(
            write_allowlist=frozenset({"Tag1"}),
            safe_state_outputs=(),
            rate_limiter=None,
        )

        # Always passes without limiter
        for _ in range(100):
            assert controller.check_rate_limit() is True

    def test_from_config(self) -> None:
        """Should create SafetyController from SafetyConfig."""
        config = SafetyConfig(
            write_allowlist=["Motor.Speed", "Pump.Flow"],
            safe_state_outputs=[
                SafeStateOutput(tag="Motor.Speed", value=0),
                SafeStateOutput(tag="Pump.Enable", value=False),
            ],
            command_rate_limit="10/s",
        )

        controller = SafetyController.from_config(config)

        assert "Motor.Speed" in controller.write_allowlist
        assert "Pump.Flow" in controller.write_allowlist
        assert len(controller.safe_state_outputs) == 2
        assert controller.rate_limiter is not None
        assert controller.rate_limiter.max_per_second == 10.0


# =============================================================================
# TagManager Safety Integration Tests
# =============================================================================


@pytest.fixture
def mock_connector() -> MagicMock:
    """Create a mock connector for tests."""
    connector = MagicMock()
    connector.read_tags = AsyncMock(return_value={"DB1.DBD0": TagValue.good(100.0)})
    connector.write_tag = AsyncMock(return_value=True)
    connector.write_tag_value = AsyncMock(return_value=True)
    return connector


@pytest.fixture
def tag_configs() -> list[TagConfig]:
    """Sample tag configurations for testing."""
    return [
        TagConfig(
            name="Motor.Speed",
            connector="plc1",
            address="DB1.DBD0",
            datatype=DataTypeConfig.FLOAT32,
            writable=True,
        ),
        TagConfig(
            name="Sensor.Temp",
            connector="plc1",
            address="DB1.DBD4",
            datatype=DataTypeConfig.FLOAT32,
            writable=True,
        ),
        TagConfig(
            name="ReadOnly.Value",
            connector="plc1",
            address="DB1.DBD8",
            datatype=DataTypeConfig.FLOAT32,
            writable=False,
        ),
    ]


class TestTagManagerSafety:
    """Tests for TagManager safety integration."""

    @pytest.mark.asyncio
    async def test_write_blocked_by_allowlist(
        self, mock_connector: MagicMock, tag_configs: list[TagConfig]
    ) -> None:
        """Write to tag not in allowlist should be blocked."""
        safety = SafetyController(
            write_allowlist=frozenset({"Motor.Speed"}),  # Sensor.Temp not allowed
            safe_state_outputs=(),
            rate_limiter=None,
        )

        tm = TagManager(
            connectors={"plc1": mock_connector},
            tags=tag_configs,
            safety=safety,
        )

        # Motor.Speed is allowed
        result1 = await tm.write_tag("Motor.Speed", 50.0)
        assert result1 is True

        # Sensor.Temp is NOT allowed
        result2 = await tm.write_tag("Sensor.Temp", 25.0)
        assert result2 is False

        # Only one actual write should happen
        assert mock_connector.write_tag_value.call_count == 1

    @pytest.mark.asyncio
    async def test_write_blocked_by_rate_limit(
        self, mock_connector: MagicMock, tag_configs: list[TagConfig]
    ) -> None:
        """Write exceeding rate limit should be blocked."""
        safety = SafetyController(
            write_allowlist=frozenset({"Motor.Speed", "Sensor.Temp"}),
            safe_state_outputs=(),
            rate_limiter=RateLimiter(max_per_second=1.0),
        )

        tm = TagManager(
            connectors={"plc1": mock_connector},
            tags=tag_configs,
            safety=safety,
        )

        # First write should succeed
        result1 = await tm.write_tag("Motor.Speed", 50.0)
        assert result1 is True

        # Second immediate write should fail (rate limit)
        result2 = await tm.write_tag("Motor.Speed", 60.0)
        assert result2 is False

        # Only one actual write
        assert mock_connector.write_tag_value.call_count == 1

    @pytest.mark.asyncio
    async def test_write_allowed_with_safety(
        self, mock_connector: MagicMock, tag_configs: list[TagConfig]
    ) -> None:
        """Write to allowed tag within rate limit should succeed."""
        safety = SafetyController(
            write_allowlist=frozenset({"Motor.Speed"}),
            safe_state_outputs=(),
            rate_limiter=RateLimiter(max_per_second=100.0),  # High limit
        )

        tm = TagManager(
            connectors={"plc1": mock_connector},
            tags=tag_configs,
            safety=safety,
        )

        result = await tm.write_tag("Motor.Speed", 75.0)

        assert result is True
        mock_connector.write_tag_value.assert_called_once()

    @pytest.mark.asyncio
    async def test_works_without_safety_controller(
        self, mock_connector: MagicMock, tag_configs: list[TagConfig]
    ) -> None:
        """TagManager should work normally without SafetyController."""
        tm = TagManager(
            connectors={"plc1": mock_connector},
            tags=tag_configs,
            # No safety parameter
        )

        # All writes should work (no safety checks)
        result = await tm.write_tag("Motor.Speed", 100.0)
        assert result is True
        mock_connector.write_tag_value.assert_called()

    @pytest.mark.asyncio
    async def test_writable_flag_still_enforced(
        self, mock_connector: MagicMock, tag_configs: list[TagConfig]
    ) -> None:
        """writable flag should still be enforced alongside safety."""
        safety = SafetyController(
            write_allowlist=frozenset({"ReadOnly.Value"}),  # In allowlist but not writable
            safe_state_outputs=(),
            rate_limiter=None,
        )

        tm = TagManager(
            connectors={"plc1": mock_connector},
            tags=tag_configs,
            safety=safety,
        )

        # Should fail because writable=False, even though in allowlist
        result = await tm.write_tag("ReadOnly.Value", 999.0)
        assert result is False


# =============================================================================
# ServiceManager Emergency Stop Tests
# =============================================================================


@pytest.fixture
def mock_tag_manager_for_estop() -> MagicMock:
    """Create mock TagManager for emergency stop tests."""
    tm = MagicMock()
    tm.write_tag = AsyncMock(return_value=True)
    tm.read_tag = AsyncMock(return_value=TagValue.good(0))
    tm.get_value = MagicMock(return_value=TagValue.good(0))
    tm.subscribe = MagicMock()
    tm.unsubscribe = MagicMock()
    return tm


@pytest.fixture
def service_configs() -> list[ServiceConfig]:
    """Sample service configurations for testing."""
    return [
        ServiceConfig(
            name="Reactor",
            mode=ProxyMode.THICK,
        ),
        ServiceConfig(
            name="Pump",
            mode=ProxyMode.THICK,
        ),
    ]


class TestServiceManagerEmergencyStop:
    """Tests for ServiceManager emergency_stop() method."""

    @pytest.mark.asyncio
    async def test_emergency_stop_sets_safe_values(
        self, mock_tag_manager_for_estop: MagicMock, service_configs: list[ServiceConfig]
    ) -> None:
        """emergency_stop() should write all safe state outputs."""
        safety = SafetyController(
            write_allowlist=frozenset({"Motor.Speed", "Pump.Enable", "Valve.Pos"}),
            safe_state_outputs=(
                ("Motor.Speed", 0),
                ("Pump.Enable", False),
                ("Valve.Pos", 0.0),
            ),
            rate_limiter=None,
        )

        sm = ServiceManager(
            tag_manager=mock_tag_manager_for_estop,
            services=service_configs,
            safety=safety,
        )

        await sm.emergency_stop()

        # Verify all safe values were written
        write_calls = mock_tag_manager_for_estop.write_tag.call_args_list
        written_tags = {call[0][0]: call[0][1] for call in write_calls}

        assert written_tags.get("Motor.Speed") == 0
        assert written_tags.get("Pump.Enable") is False
        assert written_tags.get("Valve.Pos") == 0.0

    @pytest.mark.asyncio
    async def test_emergency_stop_aborts_all_services(
        self, mock_tag_manager_for_estop: MagicMock, service_configs: list[ServiceConfig]
    ) -> None:
        """emergency_stop() should abort all services."""
        safety = SafetyController(
            write_allowlist=frozenset(),
            safe_state_outputs=(),
            rate_limiter=None,
        )

        sm = ServiceManager(
            tag_manager=mock_tag_manager_for_estop,
            services=service_configs,
            safety=safety,
        )

        # Start services so they can be aborted
        await sm.send_command("Reactor", PackMLCommand.START)
        await sm.send_command("Pump", PackMLCommand.START)

        await sm.emergency_stop()

        # Both services should be in ABORTING or ABORTED state
        reactor_state = sm.get_service_state("Reactor")
        pump_state = sm.get_service_state("Pump")

        assert reactor_state in (PackMLState.ABORTING, PackMLState.ABORTED)
        assert pump_state in (PackMLState.ABORTING, PackMLState.ABORTED)

    @pytest.mark.asyncio
    async def test_emergency_stop_without_safety_is_noop(
        self, mock_tag_manager_for_estop: MagicMock, service_configs: list[ServiceConfig]
    ) -> None:
        """emergency_stop() without SafetyController should be a no-op."""
        sm = ServiceManager(
            tag_manager=mock_tag_manager_for_estop,
            services=service_configs,
            # No safety parameter
        )

        # Should not raise
        await sm.emergency_stop()

        # No writes should happen from emergency_stop itself
        # (The actual write count depends on whether any hooks are configured)

    @pytest.mark.asyncio
    async def test_emergency_stop_continues_on_write_failure(
        self, mock_tag_manager_for_estop: MagicMock, service_configs: list[ServiceConfig]
    ) -> None:
        """emergency_stop() should continue even if some writes fail."""
        mock_tag_manager_for_estop.write_tag = AsyncMock(side_effect=[False, True, True])

        safety = SafetyController(
            write_allowlist=frozenset({"Tag1", "Tag2", "Tag3"}),
            safe_state_outputs=(
                ("Tag1", 0),  # This will fail
                ("Tag2", 0),  # This will succeed
                ("Tag3", 0),  # This will succeed
            ),
            rate_limiter=None,
        )

        sm = ServiceManager(
            tag_manager=mock_tag_manager_for_estop,
            services=service_configs,
            safety=safety,
        )

        # Should not raise despite first write failing
        await sm.emergency_stop()

        # All three writes should have been attempted
        assert mock_tag_manager_for_estop.write_tag.call_count == 3

    @pytest.mark.asyncio
    async def test_emergency_stop_with_persistence_logs_event(
        self, mock_tag_manager_for_estop: MagicMock, service_configs: list[ServiceConfig]
    ) -> None:
        """emergency_stop() should log to command audit log if persistence available."""
        from mtp_gateway.adapters.persistence import PersistenceRepository

        repo = PersistenceRepository(db_path=":memory:")
        await repo.initialize()

        safety = SafetyController(
            write_allowlist=frozenset({"Motor.Speed"}),
            safe_state_outputs=(("Motor.Speed", 0),),
            rate_limiter=None,
        )

        sm = ServiceManager(
            tag_manager=mock_tag_manager_for_estop,
            services=service_configs,
            persistence=repo,
            safety=safety,
        )

        await sm.emergency_stop()

        # Allow background tasks to complete
        await asyncio.sleep(0.1)

        # Check audit log for emergency stop event
        now = datetime.now(timezone.utc)
        from datetime import timedelta
        logs = await repo.get_audit_log(
            start=now - timedelta(seconds=10),
            end=now + timedelta(seconds=10),
        )

        emergency_logs = [log for log in logs if log.command_type == "EMERGENCY_STOP"]
        assert len(emergency_logs) >= 1


# =============================================================================
# Integration Tests
# =============================================================================


class TestSafetyIntegration:
    """Integration tests for safety controls."""

    @pytest.mark.asyncio
    async def test_full_safety_flow(
        self, mock_connector: MagicMock, tag_configs: list[TagConfig]
    ) -> None:
        """Test complete safety flow from config to enforcement."""
        # Create safety config like real YAML would provide
        safety_config = SafetyConfig(
            write_allowlist=["Motor.Speed"],
            safe_state_outputs=[SafeStateOutput(tag="Motor.Speed", value=0)],
            command_rate_limit="100/s",  # High limit for test
        )

        safety = SafetyController.from_config(safety_config)

        tm = TagManager(
            connectors={"plc1": mock_connector},
            tags=tag_configs,
            safety=safety,
        )

        # Allowed write works
        assert await tm.write_tag("Motor.Speed", 50.0) is True

        # Disallowed write blocked
        assert await tm.write_tag("Sensor.Temp", 25.0) is False

    @pytest.mark.asyncio
    async def test_rate_limiting_across_multiple_tags(
        self, mock_connector: MagicMock, tag_configs: list[TagConfig]
    ) -> None:
        """Rate limit should apply across all writes, not per-tag."""
        safety = SafetyController(
            write_allowlist=frozenset({"Motor.Speed", "Sensor.Temp"}),
            safe_state_outputs=(),
            rate_limiter=RateLimiter(max_per_second=1.0),
        )

        tm = TagManager(
            connectors={"plc1": mock_connector},
            tags=tag_configs,
            safety=safety,
        )

        # First write to Motor.Speed succeeds
        assert await tm.write_tag("Motor.Speed", 50.0) is True

        # Immediate write to DIFFERENT tag should still fail (shared rate limit)
        assert await tm.write_tag("Sensor.Temp", 25.0) is False
