"""OPC UA Address Space Builder for MTP Gateway.

Builds the MTP-compliant OPC UA address space structure based on
VDI 2658. Creates folders, objects, and variables for:
- Data Assemblies
- Services
- Diagnostics
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
from asyncua import Server, ua
from asyncua.common.node import Node

from mtp_gateway.domain.model.data_assemblies import (
    DATA_ASSEMBLY_CLASSES,
    AnaServParam,
    AnaView,
    AnaVlv,
    BinDrv,
    BinServParam,
    BinView,
    BinVlv,
    DIntServParam,
    DIntView,
    PIDCtrl,
    StringServParam,
    StringView,
)

if TYPE_CHECKING:
    from mtp_gateway.config.schema import DataAssemblyConfig, GatewayConfig, ServiceConfig

logger = structlog.get_logger(__name__)


class MTPNodeBuilder:
    """Builder for MTP-compliant OPC UA address space."""

    def __init__(self, server: Server, namespace_idx: int) -> None:
        self._server = server
        self._ns = namespace_idx
        self._nodes: dict[str, Node] = {}
        self._service_nodes: dict[str, dict[str, Node]] = {}  # {service_name: {var_name: node}}
        self._interlock_bindings: dict[str, list[str]] = {}  # {source_tag: [node_ids]}

    async def build(
        self, config: GatewayConfig
    ) -> tuple[dict[str, Node], dict[str, dict[str, Node]], dict[str, list[str]]]:
        """Build the complete MTP address space.

        Returns:
            Tuple of:
            - Dictionary mapping node IDs to Node objects
            - Dictionary mapping service names to their key control nodes
              (CommandOp, StateCur, ProcedureCur)
            - Dictionary mapping source tags to Interlock node IDs
        """
        pea_name = config.gateway.name

        # Get Objects folder
        objects = self._server.nodes.objects

        # Create PEA root folder
        pea_folder = await objects.add_folder(
            self._ns,
            f"PEA_{pea_name}",
        )
        self._register_node(f"PEA_{pea_name}", pea_folder)

        # Create main sections
        da_folder = await pea_folder.add_folder(self._ns, "DataAssemblies")
        self._register_node(f"PEA_{pea_name}.DataAssemblies", da_folder)

        services_folder = await pea_folder.add_folder(self._ns, "Services")
        self._register_node(f"PEA_{pea_name}.Services", services_folder)

        diagnostics_folder = await pea_folder.add_folder(self._ns, "Diagnostics")
        self._register_node(f"PEA_{pea_name}.Diagnostics", diagnostics_folder)

        tags_folder = await pea_folder.add_folder(self._ns, "Tags")
        self._register_node(f"PEA_{pea_name}.Tags", tags_folder)

        # Build data assemblies
        for da_config in config.mtp.data_assemblies:
            await self._build_data_assembly(da_folder, pea_name, da_config)

        # Build services
        for service_config in config.mtp.services:
            await self._build_service(services_folder, pea_name, service_config)

        # Build tag variables
        for tag_config in config.tags:
            await self._build_tag_variable(tags_folder, pea_name, tag_config.name)

        # Build diagnostics
        await self._build_diagnostics(diagnostics_folder, pea_name, config)

        logger.info(
            "Address space built",
            pea_name=pea_name,
            total_nodes=len(self._nodes),
            services_with_nodes=len(self._service_nodes),
            interlock_bindings=len(self._interlock_bindings),
        )

        return self._nodes, self._service_nodes, self._interlock_bindings

    def _register_node(self, node_id: str, node: Node) -> None:
        """Register a node for later lookup."""
        self._nodes[node_id] = node

    def _make_node_id(self, *parts: str) -> str:
        """Create a deterministic node ID from path parts."""
        return ".".join(parts)

    async def _build_data_assembly(
        self,
        parent: Node,
        pea_name: str,
        config: DataAssemblyConfig,
    ) -> None:
        """Build a data assembly object with its variables."""
        da_name = config.name
        base_path = f"PEA_{pea_name}.DataAssemblies.{da_name}"

        # Create object for data assembly
        da_obj = await parent.add_object(self._ns, da_name)
        self._register_node(base_path, da_obj)

        # Add type-specific variables based on data assembly type
        da_type = config.type

        if da_type in ("AnaView", "AnaServParam", "AnaVlv", "AnaDrv"):
            # Analog value
            await self._add_analog_variables(da_obj, base_path, config)

        elif da_type in ("BinView", "BinServParam", "BinVlv", "BinDrv"):
            # Binary value
            await self._add_binary_variables(da_obj, base_path, config)

        elif da_type in ("DIntView", "DIntServParam"):
            # Integer value
            await self._add_integer_variables(da_obj, base_path, config)

        elif da_type == "StringView":
            # String value
            await self._add_string_variables(da_obj, base_path, config)

        elif da_type == "PIDCtrl":
            # PID controller
            await self._add_pid_variables(da_obj, base_path, config)

        # Add common WQC (worst quality code)
        await self._add_variable(da_obj, base_path, "WQC", 0, ua.VariantType.UInt32)

    async def _add_analog_variables(
        self,
        parent: Node,
        base_path: str,
        config: DataAssemblyConfig,
    ) -> None:
        """Add variables for analog data assemblies."""
        # Primary value
        await self._add_variable(parent, base_path, "V", 0.0, ua.VariantType.Float)

        # Scale limits
        v_scl_min = config.v_scl_min if config.v_scl_min is not None else 0.0
        v_scl_max = config.v_scl_max if config.v_scl_max is not None else 100.0
        await self._add_variable(parent, base_path, "VSclMin", v_scl_min, ua.VariantType.Float)
        await self._add_variable(parent, base_path, "VSclMax", v_scl_max, ua.VariantType.Float)

        # Engineering unit
        v_unit = config.v_unit if config.v_unit is not None else 0
        await self._add_variable(parent, base_path, "VUnit", v_unit, ua.VariantType.UInt32)

        # For ServParam types, add internal value and request
        if "ServParam" in config.type:
            await self._add_variable(parent, base_path, "VInt", 0.0, ua.VariantType.Float)
            await self._add_variable(parent, base_path, "VReq", 0.0, ua.VariantType.Float)
            await self._add_variable(parent, base_path, "VOpMin", 0.0, ua.VariantType.Float)
            await self._add_variable(parent, base_path, "VOpMax", 100.0, ua.VariantType.Float)
            await self._add_variable(parent, base_path, "SrcMode", 0, ua.VariantType.UInt32)

        # For active elements, add feedback
        if config.type in ("AnaVlv", "AnaDrv"):
            await self._add_variable(parent, base_path, "VFbk", 0.0, ua.VariantType.Float)
            await self._add_variable(parent, base_path, "OpMode", 0, ua.VariantType.UInt32)
            await self._add_variable(parent, base_path, "Interlock", 0, ua.VariantType.UInt32)
            await self._add_variable(parent, base_path, "Permit", 1, ua.VariantType.UInt32)

            # Register interlock binding for syncing with source tag
            if config.interlock_binding:
                interlock_node_id = f"{base_path}.Interlock"
                source_tag = config.interlock_binding.source_tag
                if source_tag not in self._interlock_bindings:
                    self._interlock_bindings[source_tag] = []
                self._interlock_bindings[source_tag].append(interlock_node_id)

    async def _add_binary_variables(
        self,
        parent: Node,
        base_path: str,
        config: DataAssemblyConfig,
    ) -> None:
        """Add variables for binary data assemblies."""
        # Primary value
        await self._add_variable(parent, base_path, "V", False, ua.VariantType.Boolean)

        # State texts
        v_state_0 = config.v_state_0 if config.v_state_0 else "Off"
        v_state_1 = config.v_state_1 if config.v_state_1 else "On"
        await self._add_variable(parent, base_path, "VState0", v_state_0, ua.VariantType.String)
        await self._add_variable(parent, base_path, "VState1", v_state_1, ua.VariantType.String)

        # For ServParam types
        if "ServParam" in config.type:
            await self._add_variable(parent, base_path, "VInt", False, ua.VariantType.Boolean)
            await self._add_variable(parent, base_path, "VReq", False, ua.VariantType.Boolean)
            await self._add_variable(parent, base_path, "SrcMode", 0, ua.VariantType.UInt32)

        # For valve/drive types
        if config.type in ("BinVlv", "BinDrv"):
            await self._add_variable(parent, base_path, "VFbkOpen", False, ua.VariantType.Boolean)
            await self._add_variable(parent, base_path, "VFbkClose", False, ua.VariantType.Boolean)
            await self._add_variable(parent, base_path, "OpMode", 0, ua.VariantType.UInt32)
            await self._add_variable(parent, base_path, "Interlock", 0, ua.VariantType.UInt32)
            await self._add_variable(parent, base_path, "Permit", 1, ua.VariantType.UInt32)
            await self._add_variable(parent, base_path, "MonPosErr", False, ua.VariantType.Boolean)

            # Register interlock binding for syncing with source tag
            if config.interlock_binding:
                interlock_node_id = f"{base_path}.Interlock"
                source_tag = config.interlock_binding.source_tag
                if source_tag not in self._interlock_bindings:
                    self._interlock_bindings[source_tag] = []
                self._interlock_bindings[source_tag].append(interlock_node_id)

    async def _add_integer_variables(
        self,
        parent: Node,
        base_path: str,
        config: DataAssemblyConfig,
    ) -> None:
        """Add variables for integer data assemblies."""
        await self._add_variable(parent, base_path, "V", 0, ua.VariantType.Int32)

        v_scl_min = int(config.v_scl_min) if config.v_scl_min is not None else 0
        v_scl_max = int(config.v_scl_max) if config.v_scl_max is not None else 65535
        await self._add_variable(parent, base_path, "VSclMin", v_scl_min, ua.VariantType.Int32)
        await self._add_variable(parent, base_path, "VSclMax", v_scl_max, ua.VariantType.Int32)

        v_unit = config.v_unit if config.v_unit is not None else 0
        await self._add_variable(parent, base_path, "VUnit", v_unit, ua.VariantType.UInt32)

        if "ServParam" in config.type:
            await self._add_variable(parent, base_path, "VInt", 0, ua.VariantType.Int32)
            await self._add_variable(parent, base_path, "VReq", 0, ua.VariantType.Int32)
            await self._add_variable(parent, base_path, "VOpMin", 0, ua.VariantType.Int32)
            await self._add_variable(parent, base_path, "VOpMax", 65535, ua.VariantType.Int32)

    async def _add_string_variables(
        self,
        parent: Node,
        base_path: str,
        config: DataAssemblyConfig,
    ) -> None:
        """Add variables for string data assemblies."""
        await self._add_variable(parent, base_path, "V", "", ua.VariantType.String)

        if "ServParam" in config.type:
            await self._add_variable(parent, base_path, "VInt", "", ua.VariantType.String)

    async def _add_pid_variables(
        self,
        parent: Node,
        base_path: str,
        config: DataAssemblyConfig,
    ) -> None:
        """Add variables for PID controller."""
        # Process variable
        await self._add_variable(parent, base_path, "PV", 0.0, ua.VariantType.Float)
        await self._add_variable(parent, base_path, "PVSclMin", 0.0, ua.VariantType.Float)
        await self._add_variable(parent, base_path, "PVSclMax", 100.0, ua.VariantType.Float)
        await self._add_variable(parent, base_path, "PVUnit", 0, ua.VariantType.UInt32)

        # Setpoint
        await self._add_variable(parent, base_path, "SP", 0.0, ua.VariantType.Float)
        await self._add_variable(parent, base_path, "SPInt", 0.0, ua.VariantType.Float)
        await self._add_variable(parent, base_path, "SPSclMin", 0.0, ua.VariantType.Float)
        await self._add_variable(parent, base_path, "SPSclMax", 100.0, ua.VariantType.Float)

        # Output (manipulated variable)
        await self._add_variable(parent, base_path, "MV", 0.0, ua.VariantType.Float)
        await self._add_variable(parent, base_path, "MVSclMin", 0.0, ua.VariantType.Float)
        await self._add_variable(parent, base_path, "MVSclMax", 100.0, ua.VariantType.Float)
        await self._add_variable(parent, base_path, "MVUnit", 0, ua.VariantType.UInt32)

        # Tuning
        await self._add_variable(parent, base_path, "Gain", 1.0, ua.VariantType.Float)
        await self._add_variable(parent, base_path, "Ti", 10.0, ua.VariantType.Float)
        await self._add_variable(parent, base_path, "Td", 0.0, ua.VariantType.Float)

        # Mode
        await self._add_variable(parent, base_path, "OpMode", 0, ua.VariantType.UInt32)
        await self._add_variable(parent, base_path, "ManMode", False, ua.VariantType.Boolean)

    async def _add_variable(
        self,
        parent: Node,
        base_path: str,
        name: str,
        initial_value: Any,
        variant_type: ua.VariantType,
    ) -> Node:
        """Add a variable node to the address space."""
        node_id = f"{base_path}.{name}"

        var = await parent.add_variable(
            self._ns,
            name,
            initial_value,
            varianttype=variant_type,
        )
        await var.set_writable()

        self._register_node(node_id, var)
        return var

    async def _build_service(
        self,
        parent: Node,
        pea_name: str,
        config: ServiceConfig,
    ) -> None:
        """Build a service object with its structure."""
        service_name = config.name
        base_path = f"PEA_{pea_name}.Services.{service_name}"

        # Create service object
        service_obj = await parent.add_object(self._ns, service_name)
        self._register_node(base_path, service_obj)

        # State machine variables (per VDI 2658-4)
        # Store key control nodes for ServiceManager integration
        command_op_node = await self._add_variable(
            service_obj, base_path, "CommandOp", 0, ua.VariantType.UInt32
        )
        await self._add_variable(
            service_obj, base_path, "CommandInt", 0, ua.VariantType.UInt32
        )
        await self._add_variable(
            service_obj, base_path, "CommandExt", 0, ua.VariantType.UInt32
        )
        state_cur_node = await self._add_variable(
            service_obj, base_path, "StateCur", 0, ua.VariantType.UInt32
        )
        await self._add_variable(
            service_obj, base_path, "StateChannel", 0, ua.VariantType.UInt32
        )
        procedure_cur_node = await self._add_variable(
            service_obj, base_path, "ProcedureCur", 0, ua.VariantType.UInt32
        )
        await self._add_variable(
            service_obj, base_path, "ProcedureReq", 0, ua.VariantType.UInt32
        )

        # Store service control node references for bidirectional integration
        self._service_nodes[service_name] = {
            "CommandOp": command_op_node,
            "StateCur": state_cur_node,
            "ProcedureCur": procedure_cur_node,
        }

        # Parameters folder
        params_folder = await service_obj.add_folder(self._ns, "Parameters")
        self._register_node(f"{base_path}.Parameters", params_folder)

        # Add parameter references
        for param in config.parameters:
            param_var = await params_folder.add_variable(
                self._ns,
                param.name,
                param.data_assembly,
                ua.VariantType.String,
            )
            self._register_node(f"{base_path}.Parameters.{param.name}", param_var)

        # Report values folder
        report_folder = await service_obj.add_folder(self._ns, "ReportValues")
        self._register_node(f"{base_path}.ReportValues", report_folder)

        for rv_name in config.report_values:
            rv_var = await report_folder.add_variable(
                self._ns,
                rv_name,
                rv_name,
                ua.VariantType.String,
            )
            self._register_node(f"{base_path}.ReportValues.{rv_name}", rv_var)

        # Procedures folder
        procs_folder = await service_obj.add_folder(self._ns, "Procedures")
        self._register_node(f"{base_path}.Procedures", procs_folder)

        for proc in config.procedures:
            proc_obj = await procs_folder.add_object(self._ns, proc.name)
            proc_path = f"{base_path}.Procedures.{proc.name}"
            self._register_node(proc_path, proc_obj)

            await self._add_variable(
                proc_obj, proc_path, "ProcedureId", proc.id, ua.VariantType.UInt32
            )
            await self._add_variable(
                proc_obj, proc_path, "IsDefault", proc.is_default, ua.VariantType.Boolean
            )

    async def _build_tag_variable(
        self,
        parent: Node,
        pea_name: str,
        tag_name: str,
    ) -> None:
        """Build a variable for direct tag access."""
        base_path = f"PEA_{pea_name}.Tags"

        var = await parent.add_variable(
            self._ns,
            tag_name,
            0.0,
            ua.VariantType.Float,
        )
        await var.set_writable()

        self._register_node(f"{base_path}.{tag_name}", var)

    async def _build_diagnostics(
        self,
        parent: Node,
        pea_name: str,
        config: GatewayConfig,
    ) -> None:
        """Build diagnostics variables."""
        base_path = f"PEA_{pea_name}.Diagnostics"

        await self._add_variable(parent, base_path, "GatewayVersion", config.gateway.version, ua.VariantType.String)
        await self._add_variable(parent, base_path, "ConnectorCount", len(config.connectors), ua.VariantType.UInt32)
        await self._add_variable(parent, base_path, "TagCount", len(config.tags), ua.VariantType.UInt32)
        await self._add_variable(parent, base_path, "ServiceCount", len(config.mtp.services), ua.VariantType.UInt32)
        await self._add_variable(parent, base_path, "HealthStatus", "OK", ua.VariantType.String)
        await self._add_variable(parent, base_path, "LastError", "", ua.VariantType.String)


async def build_address_space(
    server: Server,
    config: GatewayConfig,
    namespace_idx: int,
) -> tuple[dict[str, Node], dict[str, dict[str, Node]], dict[str, list[str]]]:
    """Build the MTP address space.

    Args:
        server: OPC UA server instance
        config: Gateway configuration
        namespace_idx: Registered namespace index

    Returns:
        Tuple of:
        - Dictionary mapping node IDs to Node objects
        - Dictionary mapping service names to their key control nodes
          (CommandOp, StateCur, ProcedureCur)
        - Dictionary mapping source tags to Interlock node IDs
    """
    builder = MTPNodeBuilder(server, namespace_idx)
    return await builder.build(config)
