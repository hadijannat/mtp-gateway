"""OPC UA Server for MTP Gateway.

Exposes an MTP-compliant OPC UA address space following VDI 2658.
Uses asyncua for the server implementation.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import structlog
from asyncua import Server, ua
from asyncua.common.callback import CallbackType, ServerItemCallback

from mtp_gateway.adapters.northbound.opcua.nodes import build_address_space
from mtp_gateway.adapters.northbound.node_ids import NodeIdStrategy
from mtp_gateway.domain.model.tags import Quality, TagValue
from mtp_gateway.domain.state_machine.packml import PackMLCommand, PackMLState

if TYPE_CHECKING:
    from asyncua import Node

    from mtp_gateway.application.service_manager import ServiceManager
    from mtp_gateway.application.tag_manager import TagManager
    from mtp_gateway.config.schema import GatewayConfig

logger = structlog.get_logger(__name__)


def quality_to_status_code(quality: Quality) -> ua.StatusCode:
    """Convert gateway Quality to OPC UA StatusCode."""
    return ua.StatusCode(quality.to_opcua_status_code())


class MTPOPCUAServer:
    """OPC UA Server exposing MTP-compliant address space.

    The server structure follows VDI 2658:
    - Root/Objects/PEA_{Name}/
        - DataAssemblies/
        - Services/
        - Diagnostics/

    When a ServiceManager is provided, bidirectional integration is enabled:
    - State changes in ServiceManager update StateCur nodes
    - CommandOp writes can trigger ServiceManager.send_command()
    """

    def __init__(
        self,
        config: GatewayConfig,
        tag_manager: TagManager,
        service_manager: ServiceManager | None = None,
    ) -> None:
        """Initialize the OPC UA server.

        Args:
            config: Gateway configuration
            tag_manager: Tag manager for value access
            service_manager: Optional ServiceManager for bidirectional integration
        """
        self._config = config
        self._tag_manager = tag_manager
        self._service_manager = service_manager
        self._server: Server | None = None
        self._namespace_idx: int = 2
        self._node_ids = NodeIdStrategy(
            namespace_uri=config.opcua.namespace_uri,
            namespace_idx=self._namespace_idx,
        )
        self._nodes: dict[str, Node] = {}
        self._service_nodes: dict[str, dict[str, Node]] = {}  # {service: {var: node}}
        self._interlock_bindings: dict[str, list[str]] = {}  # {source_tag: [node_paths]}
        self._tag_bindings: dict[str, list[str]] = {}  # {tag_name: [node_paths]}
        self._tag_nodes: dict[str, str] = {}  # {tag_name: node_path}
        self._nodeid_to_tag: dict[str, str] = {}  # {nodeid_str: tag_name}
        self._command_node_ids: dict[str, str] = {}  # {nodeid_str: service_name}
        self._procedure_node_ids: dict[str, str] = {}  # {nodeid_str: service_name}
        self._pending_procedures: dict[str, int] = {}
        self._running = False

    async def start(self) -> None:
        """Start the OPC UA server."""
        if self._running:
            return

        logger.info(
            "Starting OPC UA server",
            endpoint=self._config.opcua.endpoint,
        )

        # Create server
        self._server = Server()
        await self._server.init()

        # Configure server
        self._server.set_endpoint(self._config.opcua.endpoint)
        self._server.set_server_name(self._config.opcua.application_name)

        # Register namespace
        self._namespace_idx = await self._server.register_namespace(
            self._config.opcua.namespace_uri
        )
        self._node_ids = NodeIdStrategy(
            namespace_uri=self._config.opcua.namespace_uri,
            namespace_idx=self._namespace_idx,
        )

        # Configure security
        await self._configure_security()

        # Build address space (returns nodes, service nodes, and bindings)
        (
            self._nodes,
            self._service_nodes,
            self._interlock_bindings,
            self._tag_bindings,
            self._tag_nodes,
            _writable_nodes,
        ) = await build_address_space(
            server=self._server,
            config=self._config,
            namespace_idx=self._namespace_idx,
            namespace_uri=self._config.opcua.namespace_uri,
        )

        self._build_write_mappings()

        # Subscribe to tag changes
        self._tag_manager.subscribe(self._on_tag_change)

        # Subscribe to ServiceManager state changes if available
        if self._service_manager:
            self._service_manager.subscribe(self._on_state_change)
            logger.debug(
                "Subscribed to ServiceManager state changes",
                service_count=len(self._service_nodes),
            )

        # Subscribe to write callbacks (CommandOp, ProcedureReq, tag writes)
        self._server.subscribe_server_callback(CallbackType.PreWrite, self._on_pre_write)

        # Start the server
        await self._server.start()
        self._running = True

        logger.info(
            "OPC UA server started",
            endpoint=self._config.opcua.endpoint,
            namespace_uri=self._config.opcua.namespace_uri,
            node_count=len(self._nodes),
            service_node_count=len(self._service_nodes),
        )

    async def stop(self) -> None:
        """Stop the OPC UA server."""
        if not self._running:
            return

        logger.info("Stopping OPC UA server")

        # Unsubscribe from tag changes
        self._tag_manager.unsubscribe(self._on_tag_change)

        # Unsubscribe from ServiceManager state changes
        if self._service_manager:
            self._service_manager.unsubscribe(self._on_state_change)

        # Unsubscribe from write callbacks
        if self._server:
            self._server.unsubscribe_server_callback(CallbackType.PreWrite, self._on_pre_write)

        # Stop server
        if self._server:
            await self._server.stop()
            self._server = None

        self._running = False
        logger.info("OPC UA server stopped")

    async def _configure_security(self) -> None:
        """Configure server security settings."""
        if not self._server:
            return

        security_config = self._config.opcua.security

        # Set security policies
        policies = []

        if security_config.allow_none:
            policies.append(ua.SecurityPolicyType.NoSecurity)

        for policy in security_config.policies:
            policy_mapping = {
                "Basic128Rsa15_Sign": ua.SecurityPolicyType.Basic128Rsa15_Sign,
                "Basic128Rsa15_SignAndEncrypt": ua.SecurityPolicyType.Basic128Rsa15_SignAndEncrypt,
                "Basic256_Sign": ua.SecurityPolicyType.Basic256_Sign,
                "Basic256_SignAndEncrypt": ua.SecurityPolicyType.Basic256_SignAndEncrypt,
                "Basic256Sha256_Sign": ua.SecurityPolicyType.Basic256Sha256_Sign,
                "Basic256Sha256_SignAndEncrypt": (
                    ua.SecurityPolicyType.Basic256Sha256_SignAndEncrypt
                ),
            }
            if policy.value in policy_mapping:
                policies.append(policy_mapping[policy.value])

        if policies:
            self._server.set_security_policy(policies)

        # Load certificates if configured
        if security_config.cert_path and security_config.key_path:
            await self._server.load_certificate(str(security_config.cert_path))
            await self._server.load_private_key(str(security_config.key_path))

    def _build_write_mappings(self) -> None:
        """Build NodeId mappings for OPC UA write handling."""
        self._command_node_ids.clear()
        self._procedure_node_ids.clear()
        self._nodeid_to_tag.clear()

        for service_name, nodes in self._service_nodes.items():
            command_node = nodes.get("CommandOp")
            if command_node:
                self._command_node_ids[command_node.nodeid.to_string()] = service_name

            procedure_node = nodes.get("ProcedureReq")
            if procedure_node:
                self._procedure_node_ids[procedure_node.nodeid.to_string()] = service_name

        tag_lookup = {tag.name: tag for tag in self._config.tags}
        for tag_name, node_paths in self._tag_bindings.items():
            tag_config = tag_lookup.get(tag_name)
            if not tag_config or not tag_config.writable:
                continue
            for node_path in node_paths:
                node = self._nodes.get(node_path)
                if node:
                    self._nodeid_to_tag[node.nodeid.to_string()] = tag_name

        for tag_name, node_path in self._tag_nodes.items():
            tag_config = tag_lookup.get(tag_name)
            if not tag_config or not tag_config.writable:
                continue
            node = self._nodes.get(node_path)
            if node:
                self._nodeid_to_tag[node.nodeid.to_string()] = tag_name

    def _on_pre_write(self, event: ServerItemCallback, _dispatcher: object) -> None:
        """Handle OPC UA write requests before they are applied."""
        if not self._running:
            return

        if not isinstance(event, ServerItemCallback):
            return

        # Only handle external client writes to avoid feedback loops.
        if not event.is_external:
            return

        params = event.request_params
        if not params:
            return

        for write_value in params.NodesToWrite:
            if write_value.AttributeId != ua.AttributeIds.Value:
                continue

            node_id_str = write_value.NodeId.to_string()
            data_value = write_value.Value
            variant = data_value.Value
            value = variant.Value

            if node_id_str in self._command_node_ids:
                service_name = self._command_node_ids[node_id_str]
                asyncio.create_task(self._handle_command_value(service_name, int(value)))
                continue

            if node_id_str in self._procedure_node_ids:
                service_name = self._procedure_node_ids[node_id_str]
                asyncio.create_task(self._handle_procedure_value(service_name, int(value)))
                continue

            tag_name = self._nodeid_to_tag.get(node_id_str)
            if tag_name:
                asyncio.create_task(self._tag_manager.write_tag(tag_name, value))

    def _on_tag_change(self, tag_name: str, value: TagValue) -> None:
        """Handle tag value change - update OPC UA nodes.

        This is called from the tag manager when values change.
        We need to schedule the async update on the event loop.
        """
        if not self._running or not self._server:
            return

        # Update data assembly nodes bound to this tag
        for node_path in self._tag_bindings.get(tag_name, []):
            if node_path in self._nodes:
                asyncio.create_task(self._update_node_value(node_path, value))

        # Update direct tag node if present
        node_path = self._tag_nodes.get(tag_name)
        if node_path and node_path in self._nodes:
            asyncio.create_task(self._update_node_value(node_path, value))

        # Check if this tag is bound to any Interlock variables
        if tag_name in self._interlock_bindings:
            for interlock_node_path in self._interlock_bindings[tag_name]:
                if interlock_node_path in self._nodes:
                    # Convert to interlock state: 1 if interlocked (True), 0 if clear
                    interlock_value = 1 if value.value else 0
                    interlock_tag_value = TagValue(
                        value=interlock_value,
                        quality=value.quality,
                        timestamp=value.timestamp,
                        source_timestamp=value.source_timestamp,
                    )
                    asyncio.create_task(
                        self._update_node_value(interlock_node_path, interlock_tag_value)
                    )

    async def _update_node_value(self, node_id: str, value: TagValue) -> None:
        """Update an OPC UA node with a new value."""
        if node_id not in self._nodes:
            return

        node = self._nodes[node_id]

        try:
            # Create DataValue with quality and timestamps
            dv = ua.DataValue(
                Value=ua.Variant(value.value),
                StatusCode=quality_to_status_code(value.quality),
                SourceTimestamp=value.source_timestamp or value.timestamp,
                ServerTimestamp=datetime.now(timezone.utc),
            )
            await node.write_value(dv)

        except Exception as e:
            logger.warning(
                "Failed to update OPC UA node",
                node_id=node_id,
                error=str(e),
            )

    def _on_state_change(
        self, service_name: str, from_state: PackMLState, to_state: PackMLState
    ) -> None:
        """Handle service state changes from ServiceManager.

        This callback is synchronous (ServiceManager requirement), so we
        schedule the async OPC UA update using asyncio.create_task().
        """
        if not self._running:
            return

        if service_name in self._service_nodes:
            asyncio.create_task(self._update_service_state(service_name, to_state))

            logger.debug(
                "Service state change scheduled for OPC UA update",
                service=service_name,
                from_state=from_state.name,
                to_state=to_state.name,
            )

    async def _update_service_state(
        self, service_name: str, state: PackMLState
    ) -> None:
        """Update StateCur node for a service.

        Args:
            service_name: Name of the service
            state: New PackML state
        """
        nodes = self._service_nodes.get(service_name, {})
        state_cur_node = nodes.get("StateCur")

        if state_cur_node:
            try:
                await state_cur_node.write_value(
                    ua.DataValue(ua.Variant(state.value, ua.VariantType.UInt32))
                )
            except Exception as e:
                logger.warning(
                    "Failed to update StateCur node",
                    service=service_name,
                    state=state.name,
                    error=str(e),
                )

    async def _update_service_procedure(
        self, service_name: str, procedure_id: int
    ) -> None:
        """Update ProcedureCur node for a service.

        Args:
            service_name: Name of the service
            procedure_id: Current procedure ID
        """
        nodes = self._service_nodes.get(service_name, {})
        procedure_cur_node = nodes.get("ProcedureCur")

        if procedure_cur_node:
            try:
                await procedure_cur_node.write_value(
                    ua.DataValue(ua.Variant(procedure_id, ua.VariantType.UInt32))
                )
            except Exception as e:
                logger.warning(
                    "Failed to update ProcedureCur node",
                    service=service_name,
                    procedure_id=procedure_id,
                    error=str(e),
                )

    async def _handle_command_value(
        self, service_name: str, command_value: int
    ) -> None:
        """Handle a command value written to CommandOp.

        PackML commands are 1-10. Value 0 means "no command" and values
        above 10 are invalid.

        Args:
            service_name: Name of the service
            command_value: Command value (0-10)
        """
        if not self._service_manager:
            return

        # Ignore invalid command values
        if command_value < 1 or command_value > 10:
            return

        try:
            command = PackMLCommand(command_value)
            procedure_id = None
            if command == PackMLCommand.START:
                procedure_id = self._pending_procedures.pop(service_name, None)

            await self._service_manager.send_command(
                service_name,
                command,
                procedure_id=procedure_id,
            )

            if command == PackMLCommand.START and procedure_id is not None:
                await self._update_service_procedure(service_name, procedure_id)

            logger.debug(
                "Processed OPC UA command",
                service=service_name,
                command=command.name,
            )
        except ValueError:
            logger.warning(
                "Invalid command value from OPC UA",
                service=service_name,
                value=command_value,
            )
        except Exception as e:
            logger.warning(
                "Failed to process OPC UA command",
                service=service_name,
                value=command_value,
                error=str(e),
            )

    async def _handle_procedure_value(self, service_name: str, procedure_id: int) -> None:
        """Handle ProcedureReq writes by storing the next procedure selection."""
        if not self._service_manager:
            return

        if procedure_id < 0:
            logger.warning(
                "Invalid procedure ID from OPC UA",
                service=service_name,
                procedure_id=procedure_id,
            )
            return

        self._pending_procedures[service_name] = procedure_id

        logger.debug(
            "Stored procedure request",
            service=service_name,
            procedure_id=procedure_id,
        )

    def get_node(self, node_id: str) -> Node | None:
        """Get an OPC UA node by ID."""
        return self._nodes.get(node_id)

    def get_all_node_ids(self) -> list[str]:
        """Get all registered node IDs."""
        return list(self._nodes.keys())

    @property
    def is_running(self) -> bool:
        """Check if server is running."""
        return self._running

    @property
    def endpoint(self) -> str:
        """Get server endpoint URL."""
        return self._config.opcua.endpoint

    @property
    def namespace_index(self) -> int:
        """Get the registered namespace index."""
        return self._namespace_idx
