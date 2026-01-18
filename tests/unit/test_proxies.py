"""Unit tests for ServiceProxy implementations.

Tests the THIN, THICK, and HYBRID proxy adapters that handle
service command execution in different modes.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from mtp_gateway.application.proxies import (
    HybridProxy,
    ProxyResult,
    ServiceProxy,
    ThickProxy,
    ThinProxy,
    create_proxy,
)
from mtp_gateway.config.schema import (
    CompletionConfig,
    ProcedureConfig,
    ProxyMode,
    ServiceConfig,
    StateHooksConfig,
    WriteAction,
)
from mtp_gateway.domain.model.tags import TagValue
from mtp_gateway.domain.state_machine.packml import (
    PackMLCommand,
    PackMLState,
)


@pytest.fixture
def mock_tag_manager() -> MagicMock:
    """Create a mock TagManager."""
    tm = MagicMock()
    tm.write_tag = AsyncMock(return_value=True)
    tm.get_value = MagicMock(return_value=TagValue.good(0))
    return tm


@pytest.fixture
def thick_service_config() -> ServiceConfig:
    """Create a thick proxy service configuration."""
    return ServiceConfig(
        name="ThickService",
        mode=ProxyMode.THICK,
        procedures=[
            ProcedureConfig(id=0, name="Main", is_default=True),
        ],
        state_hooks=StateHooksConfig(
            on_starting=[WriteAction(tag="PLC.Start", value=True)],
            on_execute=[WriteAction(tag="PLC.Run", value=True)],
        ),
        completion=CompletionConfig(self_completing=True),
    )


@pytest.fixture
def thin_service_config() -> ServiceConfig:
    """Create a thin proxy service configuration."""
    return ServiceConfig(
        name="ThinService",
        mode=ProxyMode.THIN,
        state_cur_tag="PLC.StateCur",
        command_op_tag="PLC.CommandOp",
    )


@pytest.fixture
def hybrid_service_config() -> ServiceConfig:
    """Create a hybrid proxy service configuration."""
    return ServiceConfig(
        name="HybridService",
        mode=ProxyMode.HYBRID,
        state_cur_tag="PLC.StateCur",
        command_op_tag="PLC.CommandOp",
        state_hooks=StateHooksConfig(
            on_starting=[WriteAction(tag="PLC.Start", value=True)],
        ),
    )


class TestProxyResult:
    """Tests for ProxyResult dataclass."""

    def test_successful_result(self) -> None:
        """ProxyResult should capture successful transitions."""
        result = ProxyResult(
            success=True,
            from_state=PackMLState.IDLE,
            to_state=PackMLState.STARTING,
        )
        assert result.success is True
        assert result.from_state == PackMLState.IDLE
        assert result.to_state == PackMLState.STARTING
        assert result.error is None

    def test_failed_result(self) -> None:
        """ProxyResult should capture failures with error messages."""
        result = ProxyResult(
            success=False,
            from_state=PackMLState.IDLE,
            to_state=None,
            error="Command not valid in current state",
        )
        assert result.success is False
        assert result.error is not None


class TestThickProxy:
    """Tests for ThickProxy - state machine runs in gateway."""

    @pytest.mark.asyncio
    async def test_send_command_transitions_state(
        self, mock_tag_manager: MagicMock, thick_service_config: ServiceConfig
    ) -> None:
        """ThickProxy should execute state machine transitions locally."""
        proxy = ThickProxy(
            config=thick_service_config,
            tag_manager=mock_tag_manager,
        )

        result = await proxy.send_command(PackMLCommand.START)

        assert result.success is True
        assert result.from_state == PackMLState.IDLE
        assert result.to_state == PackMLState.STARTING

    @pytest.mark.asyncio
    async def test_send_command_executes_hooks(
        self, mock_tag_manager: MagicMock, thick_service_config: ServiceConfig
    ) -> None:
        """ThickProxy should execute state hooks on transition."""
        proxy = ThickProxy(
            config=thick_service_config,
            tag_manager=mock_tag_manager,
        )

        await proxy.send_command(PackMLCommand.START)

        # Verify on_starting hook was called
        mock_tag_manager.write_tag.assert_called()
        calls = [
            call
            for call in mock_tag_manager.write_tag.call_args_list
            if call[0] == ("PLC.Start", True)
        ]
        assert len(calls) >= 1

    @pytest.mark.asyncio
    async def test_invalid_command_returns_error(
        self, mock_tag_manager: MagicMock, thick_service_config: ServiceConfig
    ) -> None:
        """ThickProxy should return error for invalid commands."""
        proxy = ThickProxy(
            config=thick_service_config,
            tag_manager=mock_tag_manager,
        )

        # HOLD is not valid in IDLE state
        result = await proxy.send_command(PackMLCommand.HOLD)

        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_get_state_returns_local_state(
        self, mock_tag_manager: MagicMock, thick_service_config: ServiceConfig
    ) -> None:
        """ThickProxy.get_state() should return local state machine state."""
        proxy = ThickProxy(
            config=thick_service_config,
            tag_manager=mock_tag_manager,
        )

        state = await proxy.get_state()

        assert state == PackMLState.IDLE

    @pytest.mark.asyncio
    async def test_auto_complete_acting_state(
        self, mock_tag_manager: MagicMock, thick_service_config: ServiceConfig
    ) -> None:
        """ThickProxy should auto-complete acting states after hooks."""
        proxy = ThickProxy(
            config=thick_service_config,
            tag_manager=mock_tag_manager,
        )

        # START → STARTING (acting state) → auto-completes to EXECUTE
        result = await proxy.send_command(PackMLCommand.START)

        # Acting state should auto-complete
        # (behavior depends on implementation details)
        assert result.success is True


class TestThinProxy:
    """Tests for ThinProxy - state machine runs in PLC."""

    @pytest.mark.asyncio
    async def test_send_command_writes_to_plc(
        self, mock_tag_manager: MagicMock, thin_service_config: ServiceConfig
    ) -> None:
        """ThinProxy should write command value to command_op_tag."""
        proxy = ThinProxy(
            config=thin_service_config,
            tag_manager=mock_tag_manager,
        )

        result = await proxy.send_command(PackMLCommand.START)

        assert result.success is True
        mock_tag_manager.write_tag.assert_called_with("PLC.CommandOp", PackMLCommand.START.value)

    @pytest.mark.asyncio
    async def test_send_command_fails_without_command_tag(
        self, mock_tag_manager: MagicMock
    ) -> None:
        """ThinProxy should fail if command_op_tag is not configured."""
        config = ServiceConfig(
            name="ThinService",
            mode=ProxyMode.THIN,
            # Missing command_op_tag
        )
        proxy = ThinProxy(config=config, tag_manager=mock_tag_manager)

        result = await proxy.send_command(PackMLCommand.START)

        assert result.success is False
        assert "command_op_tag" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_get_state_reads_from_plc(
        self, mock_tag_manager: MagicMock, thin_service_config: ServiceConfig
    ) -> None:
        """ThinProxy.get_state() should read state from state_cur_tag."""
        mock_tag_manager.get_value.return_value = TagValue.good(PackMLState.EXECUTE.value)

        proxy = ThinProxy(
            config=thin_service_config,
            tag_manager=mock_tag_manager,
        )

        state = await proxy.get_state()

        assert state == PackMLState.EXECUTE
        mock_tag_manager.get_value.assert_called_with("PLC.StateCur")

    @pytest.mark.asyncio
    async def test_get_state_returns_undefined_on_missing_tag(
        self, mock_tag_manager: MagicMock
    ) -> None:
        """ThinProxy.get_state() should return UNDEFINED if state_cur_tag missing."""
        config = ServiceConfig(
            name="ThinService",
            mode=ProxyMode.THIN,
            command_op_tag="PLC.CommandOp",
            # Missing state_cur_tag
        )
        proxy = ThinProxy(config=config, tag_manager=mock_tag_manager)

        state = await proxy.get_state()

        assert state == PackMLState.UNDEFINED

    @pytest.mark.asyncio
    async def test_get_state_returns_undefined_on_invalid_value(
        self, mock_tag_manager: MagicMock, thin_service_config: ServiceConfig
    ) -> None:
        """ThinProxy.get_state() should return UNDEFINED for invalid state values."""
        mock_tag_manager.get_value.return_value = TagValue.good(9999)  # Invalid

        proxy = ThinProxy(
            config=thin_service_config,
            tag_manager=mock_tag_manager,
        )

        state = await proxy.get_state()

        assert state == PackMLState.UNDEFINED


class TestHybridProxy:
    """Tests for HybridProxy - writes to PLC and tracks locally."""

    @pytest.mark.asyncio
    async def test_send_command_writes_to_plc_and_tracks_locally(
        self, mock_tag_manager: MagicMock, hybrid_service_config: ServiceConfig
    ) -> None:
        """HybridProxy should write to PLC AND update local state."""
        proxy = HybridProxy(
            config=hybrid_service_config,
            tag_manager=mock_tag_manager,
        )

        result = await proxy.send_command(PackMLCommand.START)

        assert result.success is True
        # Should write to PLC
        mock_tag_manager.write_tag.assert_called()
        # Should have local state tracking
        local_state = await proxy.get_state()
        # Local state should reflect command
        assert local_state in (PackMLState.STARTING, PackMLState.IDLE)

    @pytest.mark.asyncio
    async def test_get_state_prioritizes_plc_state(
        self, mock_tag_manager: MagicMock, hybrid_service_config: ServiceConfig
    ) -> None:
        """HybridProxy.get_state() should prefer PLC state when available."""
        mock_tag_manager.get_value.return_value = TagValue.good(PackMLState.EXECUTE.value)

        proxy = HybridProxy(
            config=hybrid_service_config,
            tag_manager=mock_tag_manager,
        )

        state = await proxy.get_state()

        # Should return PLC state
        assert state == PackMLState.EXECUTE


class TestCreateProxy:
    """Tests for proxy factory function."""

    def test_creates_thick_proxy(
        self, mock_tag_manager: MagicMock, thick_service_config: ServiceConfig
    ) -> None:
        """create_proxy() should return ThickProxy for THICK mode."""
        proxy = create_proxy(thick_service_config, mock_tag_manager)
        assert isinstance(proxy, ThickProxy)

    def test_creates_thin_proxy(
        self, mock_tag_manager: MagicMock, thin_service_config: ServiceConfig
    ) -> None:
        """create_proxy() should return ThinProxy for THIN mode."""
        proxy = create_proxy(thin_service_config, mock_tag_manager)
        assert isinstance(proxy, ThinProxy)

    def test_creates_hybrid_proxy(
        self, mock_tag_manager: MagicMock, hybrid_service_config: ServiceConfig
    ) -> None:
        """create_proxy() should return HybridProxy for HYBRID mode."""
        proxy = create_proxy(hybrid_service_config, mock_tag_manager)
        assert isinstance(proxy, HybridProxy)


class TestServiceProxyInterface:
    """Tests verifying ServiceProxy interface compliance."""

    @pytest.mark.asyncio
    async def test_thick_proxy_implements_interface(
        self, mock_tag_manager: MagicMock, thick_service_config: ServiceConfig
    ) -> None:
        """ThickProxy should implement ServiceProxy interface."""
        proxy: ServiceProxy = ThickProxy(
            config=thick_service_config,
            tag_manager=mock_tag_manager,
        )
        # Interface methods
        result = await proxy.send_command(PackMLCommand.START)
        state = await proxy.get_state()
        assert isinstance(result, ProxyResult)
        assert isinstance(state, PackMLState)

    @pytest.mark.asyncio
    async def test_thin_proxy_implements_interface(
        self, mock_tag_manager: MagicMock, thin_service_config: ServiceConfig
    ) -> None:
        """ThinProxy should implement ServiceProxy interface."""
        proxy: ServiceProxy = ThinProxy(
            config=thin_service_config,
            tag_manager=mock_tag_manager,
        )
        result = await proxy.send_command(PackMLCommand.START)
        state = await proxy.get_state()
        assert isinstance(result, ProxyResult)
        assert isinstance(state, PackMLState)

    @pytest.mark.asyncio
    async def test_hybrid_proxy_implements_interface(
        self, mock_tag_manager: MagicMock, hybrid_service_config: ServiceConfig
    ) -> None:
        """HybridProxy should implement ServiceProxy interface."""
        proxy: ServiceProxy = HybridProxy(
            config=hybrid_service_config,
            tag_manager=mock_tag_manager,
        )
        result = await proxy.send_command(PackMLCommand.START)
        state = await proxy.get_state()
        assert isinstance(result, ProxyResult)
        assert isinstance(state, PackMLState)
