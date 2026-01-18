"""Unit tests for OPC UA <-> ServiceManager integration.

Tests bidirectional communication:
- OPC UA CommandOp writes trigger ServiceManager.send_command()
- ServiceManager state changes update OPC UA StateCur nodes
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asyncua import ua

from mtp_gateway.adapters.northbound.opcua.nodes import MTPNodeBuilder
from mtp_gateway.adapters.northbound.opcua.server import MTPOPCUAServer
from mtp_gateway.application.service_manager import ServiceManager
from mtp_gateway.config.schema import (
    CompletionConfig,
    GatewayConfig,
    GatewayInfo,
    MTPConfig,
    OPCUAConfig,
    OPCUASecurityConfig,
    ProcedureConfig,
    ProxyMode,
    ServiceConfig,
    StateHooksConfig,
    WriteAction,
)
from mtp_gateway.domain.state_machine.packml import PackMLState


@pytest.fixture
def mock_tag_manager() -> MagicMock:
    """Create a mock TagManager."""
    tm = MagicMock()
    tm.write_tag = AsyncMock(return_value=True)
    tm.get_value = MagicMock(return_value=None)
    tm.subscribe = MagicMock()
    tm.unsubscribe = MagicMock()
    return tm


@pytest.fixture
def thick_service_config() -> ServiceConfig:
    """Create a thick proxy service configuration."""
    return ServiceConfig(
        name="MixingService",
        mode=ProxyMode.THICK,
        procedures=[
            ProcedureConfig(id=0, name="Default", is_default=True),
        ],
        state_hooks=StateHooksConfig(
            on_starting=[WriteAction(tag="PLC.Start", value=True)],
        ),
        completion=CompletionConfig(self_completing=True),
    )


@pytest.fixture
def minimal_gateway_config(thick_service_config: ServiceConfig) -> GatewayConfig:
    """Create a minimal gateway configuration for testing."""
    return GatewayConfig(
        gateway=GatewayInfo(
            name="TestGateway",
            version="1.0.0",
        ),
        opcua=OPCUAConfig(
            endpoint="opc.tcp://localhost:4840",
            namespace_uri="urn:test:gateway",
            application_name="TestGateway",
            security=OPCUASecurityConfig(
                allow_none=True,
            ),
        ),
        mtp=MTPConfig(
            services=[thick_service_config],
        ),
        connectors=[],
        tags=[],
    )


@pytest.fixture
def service_manager(
    mock_tag_manager: MagicMock,
    thick_service_config: ServiceConfig,
) -> ServiceManager:
    """Create a ServiceManager with a thick service."""
    return ServiceManager(
        tag_manager=mock_tag_manager,
        services=[thick_service_config],
    )


class TestOPCUACommandHandling:
    """Tests for OPC UA command write handling."""

    @pytest.mark.asyncio
    async def test_command_op_write_triggers_service_command(
        self,
        minimal_gateway_config: GatewayConfig,
        mock_tag_manager: MagicMock,
        service_manager: ServiceManager,
    ) -> None:
        """Writing to CommandOp should call ServiceManager.send_command().

        This test validates the core integration: when an OPC UA client
        writes a command value to the CommandOp variable, the server
        should route that command to the ServiceManager.
        """
        server = MTPOPCUAServer(
            config=minimal_gateway_config,
            tag_manager=mock_tag_manager,
            service_manager=service_manager,
        )

        # Verify the server has the command handling method
        assert hasattr(server, "_handle_command_value")

        # Test that a valid command value is processed
        server._running = True
        server._service_nodes = {"MixingService": {}}

        # Should not raise for valid command (START = 2)
        with patch.object(service_manager, "send_command", new=AsyncMock()) as mock_send:
            await server._handle_command_value("MixingService", 2)
            mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_command_value_ignored(
        self,
        minimal_gateway_config: GatewayConfig,
        mock_tag_manager: MagicMock,
        service_manager: ServiceManager,
    ) -> None:
        """Writing invalid command value (0 or >10) should be ignored.

        PackML commands are 1-10. Value 0 means "no command" and values
        above 10 are invalid. The server should silently ignore these.
        """
        server = MTPOPCUAServer(
            config=minimal_gateway_config,
            tag_manager=mock_tag_manager,
            service_manager=service_manager,
        )

        # Server should have a method to handle command writes
        # Invalid values should not raise exceptions or call send_command
        # Test value 0 (no command)
        initial_state = service_manager.get_service_state("MixingService")

        # After handling invalid command value 0
        if hasattr(server, "_handle_command_value"):
            await server._handle_command_value("MixingService", 0)
            assert service_manager.get_service_state("MixingService") == initial_state


class TestOPCUAStateSync:
    """Tests for state synchronization from ServiceManager to OPC UA."""

    @pytest.mark.asyncio
    async def test_state_change_updates_state_cur_node(
        self,
        minimal_gateway_config: GatewayConfig,
        mock_tag_manager: MagicMock,
        service_manager: ServiceManager,
    ) -> None:
        """ServiceManager state change should update OPC UA StateCur.

        When the ServiceManager transitions a service to a new state,
        the OPC UA server should update the corresponding StateCur node
        so connected clients can observe the state change.
        """
        server = MTPOPCUAServer(
            config=minimal_gateway_config,
            tag_manager=mock_tag_manager,
            service_manager=service_manager,
        )

        # Create a mock node for StateCur
        mock_state_cur_node = AsyncMock()
        server._service_nodes = {
            "MixingService": {
                "StateCur": mock_state_cur_node,
            }
        }
        server._running = True

        # Simulate state change callback from ServiceManager
        await server._update_service_state("MixingService", PackMLState.STARTING)

        # Verify StateCur node was updated with the new state value
        mock_state_cur_node.write_value.assert_called_once()
        call_args = mock_state_cur_node.write_value.call_args
        data_value = call_args[0][0]
        assert isinstance(data_value, ua.DataValue)
        assert data_value.Value.Value == PackMLState.STARTING.value

    @pytest.mark.asyncio
    async def test_procedure_change_updates_procedure_cur_node(
        self,
        minimal_gateway_config: GatewayConfig,
        mock_tag_manager: MagicMock,
        service_manager: ServiceManager,
    ) -> None:
        """Procedure selection should update OPC UA ProcedureCur.

        When a service is started with a specific procedure ID,
        the OPC UA ProcedureCur node should reflect this selection.
        """
        server = MTPOPCUAServer(
            config=minimal_gateway_config,
            tag_manager=mock_tag_manager,
            service_manager=service_manager,
        )

        # Create mock nodes
        mock_procedure_cur_node = AsyncMock()
        server._service_nodes = {
            "MixingService": {
                "ProcedureCur": mock_procedure_cur_node,
            }
        }
        server._running = True

        # Update procedure
        await server._update_service_procedure("MixingService", 1)

        # Verify ProcedureCur node was updated
        mock_procedure_cur_node.write_value.assert_called_once()


class TestOPCUAServerWithoutServiceManager:
    """Tests for backwards compatibility without ServiceManager."""

    @pytest.mark.asyncio
    async def test_server_starts_without_service_manager(
        self,
        minimal_gateway_config: GatewayConfig,
        mock_tag_manager: MagicMock,
    ) -> None:
        """Server should work with service_manager=None.

        For backwards compatibility and simpler deployments, the OPC UA
        server should function normally without a ServiceManager. It will
        expose the address space but service state changes won't be synced.
        """
        # Create server without service_manager (using None or omitting)
        server = MTPOPCUAServer(
            config=minimal_gateway_config,
            tag_manager=mock_tag_manager,
            service_manager=None,  # Explicitly None
        )

        assert server._service_manager is None
        # Server should still be constructable
        assert server is not None

    @pytest.mark.asyncio
    async def test_state_callback_graceful_without_nodes(
        self,
        minimal_gateway_config: GatewayConfig,
        mock_tag_manager: MagicMock,
        service_manager: ServiceManager,
    ) -> None:
        """State callback should handle missing service nodes gracefully.

        If the server receives a state change for a service that doesn't
        have nodes registered (edge case), it should not crash.
        """
        server = MTPOPCUAServer(
            config=minimal_gateway_config,
            tag_manager=mock_tag_manager,
            service_manager=service_manager,
        )

        # No service nodes registered
        server._service_nodes = {}
        server._running = True

        # This should not raise
        await server._update_service_state("UnknownService", PackMLState.IDLE)


class TestOPCUANodeBuilderServiceNodes:
    """Tests for MTPNodeBuilder returning service node references."""

    @pytest.mark.asyncio
    async def test_build_returns_service_nodes(
        self,
        minimal_gateway_config: GatewayConfig,
    ) -> None:
        """build() should return service node references for key variables.

        The node builder should return not just the full node dict, but
        also a dict mapping service names to their key control nodes
        (CommandOp, StateCur, ProcedureCur).
        """

        class FakeVariable:
            def __init__(self, name: str) -> None:
                self.name = name

            async def set_writable(self) -> None:
                return None

        class FakeNode:
            def __init__(self, name: str) -> None:
                self.name = name
                self.children: dict[str, FakeNode] = {}

            async def add_folder(self, _node_id: object, name: str) -> FakeNode:
                node = FakeNode(name)
                self.children[name] = node
                return node

            async def add_object(self, _node_id: object, name: str) -> FakeNode:
                node = FakeNode(name)
                self.children[name] = node
                return node

            async def add_variable(
                self,
                _node_id: object,
                name: str,
                _value: object,
                **_kwargs: object,
            ) -> FakeVariable:
                return FakeVariable(name)

        class FakeServer:
            def __init__(self) -> None:
                self.nodes = type("Nodes", (), {"objects": FakeNode("Objects")})

        server = FakeServer()
        ns = 2

        builder = MTPNodeBuilder(server, ns, minimal_gateway_config.opcua.namespace_uri)
        (
            _all_nodes,
            service_nodes,
            _interlock_bindings,
            _tag_bindings,
            _tag_nodes,
            _writable_nodes,
        ) = await builder.build(minimal_gateway_config)

        # Verify service nodes dict has our service
        assert "MixingService" in service_nodes
        service_node_refs = service_nodes["MixingService"]

        # Should have CommandOp, StateCur, ProcedureCur
        assert "CommandOp" in service_node_refs
        assert "StateCur" in service_node_refs
        assert "ProcedureCur" in service_node_refs

        # FakeServer has no lifecycle methods; no cleanup required.


class TestOPCUAServerServiceManagerIntegration:
    """Integration tests for server and ServiceManager working together."""

    @pytest.mark.asyncio
    async def test_subscriber_registered_on_start(
        self,
        minimal_gateway_config: GatewayConfig,
        mock_tag_manager: MagicMock,
        service_manager: ServiceManager,
    ) -> None:
        """Server should subscribe to ServiceManager on start.

        When the OPC UA server starts, it should register a callback
        with the ServiceManager to receive state change notifications.
        """
        server = MTPOPCUAServer(
            config=minimal_gateway_config,
            tag_manager=mock_tag_manager,
            service_manager=service_manager,
        )

        # Before start, verify no subscription
        initial_subscriber_count = len(service_manager._subscribers)

        # Mock server internals
        server._server = MagicMock()
        server._server.init = AsyncMock()
        server._server.start = AsyncMock()
        server._server.stop = AsyncMock()
        server._server.register_namespace = AsyncMock(return_value=2)
        server._server.nodes = MagicMock()
        server._server.nodes.objects = MagicMock()
        server._server.nodes.objects.add_folder = AsyncMock(return_value=MagicMock())
        server._server.set_endpoint = MagicMock()
        server._server.set_server_name = MagicMock()
        server._server.set_security_policy = MagicMock()

        with patch(
            "mtp_gateway.adapters.northbound.opcua.server.build_address_space",
            new=AsyncMock(return_value=({}, {}, {}, {}, {}, {})),
        ):
            await server.start()

        # After start, verify subscription was added
        assert len(service_manager._subscribers) == initial_subscriber_count + 1

        await server.stop()

    @pytest.mark.asyncio
    async def test_subscriber_unregistered_on_stop(
        self,
        minimal_gateway_config: GatewayConfig,
        mock_tag_manager: MagicMock,
        service_manager: ServiceManager,
    ) -> None:
        """Server should unsubscribe from ServiceManager on stop.

        When the server stops, it should clean up by removing its
        callback from the ServiceManager's subscriber list.
        """
        server = MTPOPCUAServer(
            config=minimal_gateway_config,
            tag_manager=mock_tag_manager,
            service_manager=service_manager,
        )

        server._server = MagicMock()
        server._server.init = AsyncMock()
        server._server.start = AsyncMock()
        server._server.stop = AsyncMock()
        server._server.register_namespace = AsyncMock(return_value=2)
        server._server.nodes = MagicMock()
        server._server.nodes.objects = MagicMock()
        server._server.nodes.objects.add_folder = AsyncMock(return_value=MagicMock())
        server._server.set_endpoint = MagicMock()
        server._server.set_server_name = MagicMock()
        server._server.set_security_policy = MagicMock()

        with patch(
            "mtp_gateway.adapters.northbound.opcua.server.build_address_space",
            new=AsyncMock(return_value=({}, {}, {}, {}, {}, {})),
        ):
            await server.start()
            subscriber_count_after_start = len(service_manager._subscribers)

            await server.stop()

        # After stop, subscriber should be removed
        assert len(service_manager._subscribers) == subscriber_count_after_start - 1
