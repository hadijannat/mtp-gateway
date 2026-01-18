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

from mtp_gateway.adapters.northbound.node_ids import NodeIdStrategy
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
    from mtp_gateway.config.schema import (
        DataAssemblyConfig,
        GatewayConfig,
        ServiceConfig,
        TagConfig,
    )

logger = structlog.get_logger(__name__)


def _variant_type_for_tag(tag_config: "TagConfig") -> ua.VariantType:
    """Map TagConfig datatype to OPC UA VariantType."""
    datatype = tag_config.datatype
    if datatype.value == "bool":
        return ua.VariantType.Boolean
    if datatype.value in {"int16", "int32", "int64"}:
        return ua.VariantType.Int64
    if datatype.value in {"uint16", "uint32", "uint64"}:
        return ua.VariantType.UInt64
    if datatype.value in {"float32", "float64"}:
        return ua.VariantType.Double
    return ua.VariantType.String


def _default_value_for_variant(variant: ua.VariantType) -> Any:
    """Provide a sensible default value for a VariantType."""
    if variant in {ua.VariantType.Double, ua.VariantType.Float}:
        return 0.0
    if variant in {ua.VariantType.Int16, ua.VariantType.Int32, ua.VariantType.Int64}:
        return 0
    if variant in {ua.VariantType.UInt16, ua.VariantType.UInt32, ua.VariantType.UInt64}:
        return 0
    if variant == ua.VariantType.Boolean:
        return False
    return ""


class MTPNodeBuilder:
    """Builder for MTP-compliant OPC UA address space."""

    def __init__(self, server: Server, namespace_idx: int, namespace_uri: str) -> None:
        self._server = server
        self._ns = namespace_idx
        self._node_ids = NodeIdStrategy(namespace_uri=namespace_uri, namespace_idx=namespace_idx)
        self._nodes: dict[str, Node] = {}
        self._service_nodes: dict[str, dict[str, Node]] = {}  # {service_name: {var_name: node}}
        self._interlock_bindings: dict[str, list[str]] = {}  # {source_tag: [node_paths]}
        self._tag_bindings: dict[str, list[str]] = {}  # {tag_name: [node_paths]}
        self._tag_nodes: dict[str, str] = {}  # {tag_name: node_path}
        self._writable_nodes: dict[str, str] = {}  # {node_id_str: tag_name}

    async def build(
        self, config: GatewayConfig
    ) -> tuple[
        dict[str, Node],
        dict[str, dict[str, Node]],
        dict[str, list[str]],
        dict[str, list[str]],
        dict[str, str],
        dict[str, str],
    ]:
        """Build the complete MTP address space.

        Returns:
            Tuple of:
            - Dictionary mapping node IDs to Node objects
            - Dictionary mapping service names to their key control nodes
              (CommandOp, StateCur, ProcedureCur)
            - Dictionary mapping source tags to Interlock node paths
            - Dictionary mapping tag names to bound node paths
            - Dictionary mapping tag names to tag node paths
            - Dictionary mapping writable node IDs to tag names
        """
        pea_name = config.gateway.name
        tag_lookup = {tag.name: tag for tag in config.tags}
        pea_root = f"PEA_{pea_name}"

        # Get Objects folder
        objects = self._server.nodes.objects

        # Create PEA root folder
        pea_path = self._node_ids.path(pea_root)
        pea_folder = await objects.add_folder(self._node_ids.ua_node_id(pea_path), pea_root)
        self._register_node(pea_path, pea_folder)

        # Create main sections
        da_path = self._node_ids.path(pea_root, "DataAssemblies")
        da_folder = await pea_folder.add_folder(
            self._node_ids.ua_node_id(da_path),
            "DataAssemblies",
        )
        self._register_node(da_path, da_folder)

        services_path = self._node_ids.path(pea_root, "Services")
        services_folder = await pea_folder.add_folder(
            self._node_ids.ua_node_id(services_path),
            "Services",
        )
        self._register_node(services_path, services_folder)

        diagnostics_path = self._node_ids.path(pea_root, "Diagnostics")
        diagnostics_folder = await pea_folder.add_folder(
            self._node_ids.ua_node_id(diagnostics_path),
            "Diagnostics",
        )
        self._register_node(diagnostics_path, diagnostics_folder)

        tags_path = self._node_ids.path(pea_root, "Tags")
        tags_folder = await pea_folder.add_folder(
            self._node_ids.ua_node_id(tags_path),
            "Tags",
        )
        self._register_node(tags_path, tags_folder)

        # Build data assemblies
        for da_config in config.mtp.data_assemblies:
            await self._build_data_assembly(da_folder, pea_root, da_config, tag_lookup)

        # Build services
        for service_config in config.mtp.services:
            await self._build_service(services_folder, pea_root, service_config)

        # Build tag variables
        for tag_config in config.tags:
            await self._build_tag_variable(tags_folder, pea_root, tag_config)

        # Build diagnostics
        await self._build_diagnostics(diagnostics_folder, pea_root, config)

        logger.info(
            "Address space built",
            pea_name=pea_name,
            total_nodes=len(self._nodes),
            services_with_nodes=len(self._service_nodes),
            interlock_bindings=len(self._interlock_bindings),
        )

        return (
            self._nodes,
            self._service_nodes,
            self._interlock_bindings,
            self._tag_bindings,
            self._tag_nodes,
            self._writable_nodes,
        )

    def _register_node(self, node_id: str, node: Node) -> None:
        """Register a node for later lookup."""
        self._nodes[node_id] = node

    async def _build_data_assembly(
        self,
        parent: Node,
        pea_root: str,
        config: DataAssemblyConfig,
        tag_lookup: dict[str, "TagConfig"],
    ) -> None:
        """Build a data assembly object with its variables."""
        da_name = config.name
        base_path = self._node_ids.path(pea_root, "DataAssemblies", da_name)
        binding_writable = {
            attr: tag_lookup[tag_name].writable
            for attr, tag_name in config.bindings.items()
            if tag_name in tag_lookup
        }
        for attr_name, tag_name in config.bindings.items():
            node_path = self._node_ids.path(base_path, attr_name)
            self._tag_bindings.setdefault(tag_name, []).append(node_path)

        # Create object for data assembly
        da_obj = await parent.add_object(self._node_ids.ua_node_id(base_path), da_name)
        self._register_node(base_path, da_obj)

        # Add type-specific variables based on data assembly type
        da_type = config.type

        if da_type in ("AnaView", "AnaServParam", "AnaVlv", "AnaDrv"):
            # Analog value
            await self._add_analog_variables(da_obj, base_path, config, binding_writable)

        elif da_type in ("BinView", "BinServParam", "BinVlv", "BinDrv"):
            # Binary value
            await self._add_binary_variables(da_obj, base_path, config, binding_writable)

        elif da_type in ("DIntView", "DIntServParam"):
            # Integer value
            await self._add_integer_variables(da_obj, base_path, config, binding_writable)

        elif da_type == "StringView":
            # String value
            await self._add_string_variables(da_obj, base_path, config, binding_writable)

        elif da_type == "PIDCtrl":
            # PID controller
            await self._add_pid_variables(da_obj, base_path, config, binding_writable)

        # Add common WQC (worst quality code)
        await self._add_variable(
            da_obj,
            base_path,
            "WQC",
            0,
            ua.VariantType.UInt32,
            writable=False,
        )

    async def _add_analog_variables(
        self,
        parent: Node,
        base_path: str,
        config: DataAssemblyConfig,
        binding_writable: dict[str, bool],
    ) -> None:
        """Add variables for analog data assemblies."""
        # Primary value
        await self._add_variable(
            parent,
            base_path,
            "V",
            0.0,
            ua.VariantType.Float,
            writable=binding_writable.get("V", False),
        )

        # Scale limits
        v_scl_min = config.v_scl_min if config.v_scl_min is not None else 0.0
        v_scl_max = config.v_scl_max if config.v_scl_max is not None else 100.0
        await self._add_variable(
            parent,
            base_path,
            "VSclMin",
            v_scl_min,
            ua.VariantType.Float,
            writable=False,
        )
        await self._add_variable(
            parent,
            base_path,
            "VSclMax",
            v_scl_max,
            ua.VariantType.Float,
            writable=False,
        )

        # Engineering unit
        v_unit = config.v_unit if config.v_unit is not None else 0
        await self._add_variable(
            parent,
            base_path,
            "VUnit",
            v_unit,
            ua.VariantType.UInt32,
            writable=False,
        )

        # For ServParam types, add internal value and request
        if "ServParam" in config.type:
            await self._add_variable(
                parent,
                base_path,
                "VInt",
                0.0,
                ua.VariantType.Float,
                writable=binding_writable.get("VInt", False),
            )
            await self._add_variable(
                parent,
                base_path,
                "VReq",
                0.0,
                ua.VariantType.Float,
                writable=binding_writable.get("VReq", False),
            )
            await self._add_variable(
                parent,
                base_path,
                "VOpMin",
                0.0,
                ua.VariantType.Float,
                writable=False,
            )
            await self._add_variable(
                parent,
                base_path,
                "VOpMax",
                100.0,
                ua.VariantType.Float,
                writable=False,
            )
            await self._add_variable(
                parent,
                base_path,
                "SrcMode",
                0,
                ua.VariantType.UInt32,
                writable=False,
            )

        # For active elements, add feedback
        if config.type in ("AnaVlv", "AnaDrv"):
            await self._add_variable(
                parent,
                base_path,
                "VFbk",
                0.0,
                ua.VariantType.Float,
                writable=binding_writable.get("VFbk", False),
            )
            await self._add_variable(
                parent,
                base_path,
                "OpMode",
                0,
                ua.VariantType.UInt32,
                writable=False,
            )
            await self._add_variable(
                parent,
                base_path,
                "Interlock",
                0,
                ua.VariantType.UInt32,
                writable=False,
            )
            await self._add_variable(
                parent,
                base_path,
                "Permit",
                1,
                ua.VariantType.UInt32,
                writable=False,
            )

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
        binding_writable: dict[str, bool],
    ) -> None:
        """Add variables for binary data assemblies."""
        # Primary value
        await self._add_variable(
            parent,
            base_path,
            "V",
            False,
            ua.VariantType.Boolean,
            writable=binding_writable.get("V", False),
        )

        # State texts
        v_state_0 = config.v_state_0 if config.v_state_0 else "Off"
        v_state_1 = config.v_state_1 if config.v_state_1 else "On"
        await self._add_variable(
            parent,
            base_path,
            "VState0",
            v_state_0,
            ua.VariantType.String,
            writable=False,
        )
        await self._add_variable(
            parent,
            base_path,
            "VState1",
            v_state_1,
            ua.VariantType.String,
            writable=False,
        )

        # For ServParam types
        if "ServParam" in config.type:
            await self._add_variable(
                parent,
                base_path,
                "VInt",
                False,
                ua.VariantType.Boolean,
                writable=binding_writable.get("VInt", False),
            )
            await self._add_variable(
                parent,
                base_path,
                "VReq",
                False,
                ua.VariantType.Boolean,
                writable=binding_writable.get("VReq", False),
            )
            await self._add_variable(
                parent,
                base_path,
                "SrcMode",
                0,
                ua.VariantType.UInt32,
                writable=False,
            )

        # For valve/drive types
        if config.type in ("BinVlv", "BinDrv"):
            await self._add_variable(
                parent,
                base_path,
                "VFbkOpen",
                False,
                ua.VariantType.Boolean,
                writable=binding_writable.get("VFbkOpen", False),
            )
            await self._add_variable(
                parent,
                base_path,
                "VFbkClose",
                False,
                ua.VariantType.Boolean,
                writable=binding_writable.get("VFbkClose", False),
            )
            await self._add_variable(
                parent,
                base_path,
                "OpMode",
                0,
                ua.VariantType.UInt32,
                writable=False,
            )
            await self._add_variable(
                parent,
                base_path,
                "Interlock",
                0,
                ua.VariantType.UInt32,
                writable=False,
            )
            await self._add_variable(
                parent,
                base_path,
                "Permit",
                1,
                ua.VariantType.UInt32,
                writable=False,
            )
            await self._add_variable(
                parent,
                base_path,
                "MonPosErr",
                False,
                ua.VariantType.Boolean,
                writable=False,
            )

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
        binding_writable: dict[str, bool],
    ) -> None:
        """Add variables for integer data assemblies."""
        await self._add_variable(
            parent,
            base_path,
            "V",
            0,
            ua.VariantType.Int32,
            writable=binding_writable.get("V", False),
        )

        v_scl_min = int(config.v_scl_min) if config.v_scl_min is not None else 0
        v_scl_max = int(config.v_scl_max) if config.v_scl_max is not None else 65535
        await self._add_variable(
            parent,
            base_path,
            "VSclMin",
            v_scl_min,
            ua.VariantType.Int32,
            writable=False,
        )
        await self._add_variable(
            parent,
            base_path,
            "VSclMax",
            v_scl_max,
            ua.VariantType.Int32,
            writable=False,
        )

        v_unit = config.v_unit if config.v_unit is not None else 0
        await self._add_variable(
            parent,
            base_path,
            "VUnit",
            v_unit,
            ua.VariantType.UInt32,
            writable=False,
        )

        if "ServParam" in config.type:
            await self._add_variable(
                parent,
                base_path,
                "VInt",
                0,
                ua.VariantType.Int32,
                writable=binding_writable.get("VInt", False),
            )
            await self._add_variable(
                parent,
                base_path,
                "VReq",
                0,
                ua.VariantType.Int32,
                writable=binding_writable.get("VReq", False),
            )
            await self._add_variable(
                parent,
                base_path,
                "VOpMin",
                0,
                ua.VariantType.Int32,
                writable=False,
            )
            await self._add_variable(
                parent,
                base_path,
                "VOpMax",
                65535,
                ua.VariantType.Int32,
                writable=False,
            )

    async def _add_string_variables(
        self,
        parent: Node,
        base_path: str,
        config: DataAssemblyConfig,
        binding_writable: dict[str, bool],
    ) -> None:
        """Add variables for string data assemblies."""
        await self._add_variable(
            parent,
            base_path,
            "V",
            "",
            ua.VariantType.String,
            writable=binding_writable.get("V", False),
        )

        if "ServParam" in config.type:
            await self._add_variable(
                parent,
                base_path,
                "VInt",
                "",
                ua.VariantType.String,
                writable=binding_writable.get("VInt", False),
            )

    async def _add_pid_variables(
        self,
        parent: Node,
        base_path: str,
        config: DataAssemblyConfig,
        binding_writable: dict[str, bool],
    ) -> None:
        """Add variables for PID controller."""
        # Process variable
        await self._add_variable(
            parent,
            base_path,
            "PV",
            0.0,
            ua.VariantType.Float,
            writable=binding_writable.get("PV", False),
        )
        await self._add_variable(
            parent,
            base_path,
            "PVSclMin",
            0.0,
            ua.VariantType.Float,
            writable=False,
        )
        await self._add_variable(
            parent,
            base_path,
            "PVSclMax",
            100.0,
            ua.VariantType.Float,
            writable=False,
        )
        await self._add_variable(
            parent,
            base_path,
            "PVUnit",
            0,
            ua.VariantType.UInt32,
            writable=False,
        )

        # Setpoint
        await self._add_variable(
            parent,
            base_path,
            "SP",
            0.0,
            ua.VariantType.Float,
            writable=binding_writable.get("SP", False),
        )
        await self._add_variable(
            parent,
            base_path,
            "SPInt",
            0.0,
            ua.VariantType.Float,
            writable=binding_writable.get("SPInt", False),
        )
        await self._add_variable(
            parent,
            base_path,
            "SPSclMin",
            0.0,
            ua.VariantType.Float,
            writable=False,
        )
        await self._add_variable(
            parent,
            base_path,
            "SPSclMax",
            100.0,
            ua.VariantType.Float,
            writable=False,
        )

        # Output (manipulated variable)
        await self._add_variable(
            parent,
            base_path,
            "MV",
            0.0,
            ua.VariantType.Float,
            writable=binding_writable.get("MV", False),
        )
        await self._add_variable(
            parent,
            base_path,
            "MVSclMin",
            0.0,
            ua.VariantType.Float,
            writable=False,
        )
        await self._add_variable(
            parent,
            base_path,
            "MVSclMax",
            100.0,
            ua.VariantType.Float,
            writable=False,
        )
        await self._add_variable(
            parent,
            base_path,
            "MVUnit",
            0,
            ua.VariantType.UInt32,
            writable=False,
        )

        # Tuning
        await self._add_variable(
            parent,
            base_path,
            "Gain",
            1.0,
            ua.VariantType.Float,
            writable=False,
        )
        await self._add_variable(
            parent,
            base_path,
            "Ti",
            10.0,
            ua.VariantType.Float,
            writable=False,
        )
        await self._add_variable(
            parent,
            base_path,
            "Td",
            0.0,
            ua.VariantType.Float,
            writable=False,
        )

        # Mode
        await self._add_variable(
            parent,
            base_path,
            "OpMode",
            0,
            ua.VariantType.UInt32,
            writable=False,
        )
        await self._add_variable(
            parent,
            base_path,
            "ManMode",
            False,
            ua.VariantType.Boolean,
            writable=False,
        )

    async def _add_variable(
        self,
        parent: Node,
        base_path: str,
        name: str,
        initial_value: Any,
        variant_type: ua.VariantType,
        *,
        writable: bool = True,
    ) -> Node:
        """Add a variable node to the address space."""
        node_path = self._node_ids.path(base_path, name)

        var = await parent.add_variable(
            self._node_ids.ua_node_id(node_path),
            name,
            initial_value,
            varianttype=variant_type,
        )
        if writable:
            await var.set_writable()

        self._register_node(node_path, var)
        return var

    async def _build_service(
        self,
        parent: Node,
        pea_root: str,
        config: ServiceConfig,
    ) -> None:
        """Build a service object with its structure."""
        service_name = config.name
        base_path = self._node_ids.path(pea_root, "Services", service_name)

        # Create service object
        service_obj = await parent.add_object(self._node_ids.ua_node_id(base_path), service_name)
        self._register_node(base_path, service_obj)

        # State machine variables (per VDI 2658-4)
        # Store key control nodes for ServiceManager integration
        command_op_node = await self._add_variable(
            service_obj, base_path, "CommandOp", 0, ua.VariantType.UInt32, writable=True
        )
        await self._add_variable(
            service_obj, base_path, "CommandInt", 0, ua.VariantType.UInt32, writable=False
        )
        await self._add_variable(
            service_obj, base_path, "CommandExt", 0, ua.VariantType.UInt32, writable=False
        )
        state_cur_node = await self._add_variable(
            service_obj, base_path, "StateCur", 0, ua.VariantType.UInt32, writable=False
        )
        await self._add_variable(
            service_obj, base_path, "StateChannel", 0, ua.VariantType.UInt32, writable=False
        )
        procedure_cur_node = await self._add_variable(
            service_obj, base_path, "ProcedureCur", 0, ua.VariantType.UInt32, writable=False
        )
        procedure_req_node = await self._add_variable(
            service_obj, base_path, "ProcedureReq", 0, ua.VariantType.UInt32, writable=True
        )

        # Store service control node references for bidirectional integration
        self._service_nodes[service_name] = {
            "CommandOp": command_op_node,
            "StateCur": state_cur_node,
            "ProcedureCur": procedure_cur_node,
            "ProcedureReq": procedure_req_node,
        }

        # Parameters folder
        params_path = self._node_ids.path(base_path, "Parameters")
        params_folder = await service_obj.add_folder(
            self._node_ids.ua_node_id(params_path),
            "Parameters",
        )
        self._register_node(params_path, params_folder)

        # Add parameter references
        for param in config.parameters:
            param_path = self._node_ids.path(base_path, "Parameters", param.name)
            param_var = await params_folder.add_variable(
                self._node_ids.ua_node_id(param_path),
                param.name,
                param.data_assembly,
                ua.VariantType.String,
            )
            self._register_node(param_path, param_var)

        # Report values folder
        report_path = self._node_ids.path(base_path, "ReportValues")
        report_folder = await service_obj.add_folder(
            self._node_ids.ua_node_id(report_path),
            "ReportValues",
        )
        self._register_node(report_path, report_folder)

        for rv_name in config.report_values:
            rv_path = self._node_ids.path(base_path, "ReportValues", rv_name)
            rv_var = await report_folder.add_variable(
                self._node_ids.ua_node_id(rv_path),
                rv_name,
                rv_name,
                ua.VariantType.String,
            )
            self._register_node(rv_path, rv_var)

        # Procedures folder
        procs_path = self._node_ids.path(base_path, "Procedures")
        procs_folder = await service_obj.add_folder(
            self._node_ids.ua_node_id(procs_path),
            "Procedures",
        )
        self._register_node(procs_path, procs_folder)

        for proc in config.procedures:
            proc_path = self._node_ids.path(base_path, "Procedures", proc.name)
            proc_obj = await procs_folder.add_object(
                self._node_ids.ua_node_id(proc_path),
                proc.name,
            )
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
        pea_root: str,
        tag_config: "TagConfig",
    ) -> None:
        """Build a variable for direct tag access."""
        base_path = self._node_ids.path(pea_root, "Tags")
        node_path = self._node_ids.path(base_path, tag_config.name)

        variant_type = _variant_type_for_tag(tag_config)
        var = await parent.add_variable(
            self._node_ids.ua_node_id(node_path),
            tag_config.name,
            _default_value_for_variant(variant_type),
            varianttype=variant_type,
        )
        if tag_config.writable:
            await var.set_writable()
            self._writable_nodes[var.nodeid.to_string()] = tag_config.name

        self._register_node(node_path, var)
        self._tag_nodes[tag_config.name] = node_path

    async def _build_diagnostics(
        self,
        parent: Node,
        pea_root: str,
        config: GatewayConfig,
    ) -> None:
        """Build diagnostics variables."""
        base_path = self._node_ids.path(pea_root, "Diagnostics")

        await self._add_variable(
            parent,
            base_path,
            "GatewayVersion",
            config.gateway.version,
            ua.VariantType.String,
            writable=False,
        )
        await self._add_variable(
            parent,
            base_path,
            "ConnectorCount",
            len(config.connectors),
            ua.VariantType.UInt32,
            writable=False,
        )
        await self._add_variable(
            parent,
            base_path,
            "TagCount",
            len(config.tags),
            ua.VariantType.UInt32,
            writable=False,
        )
        await self._add_variable(
            parent,
            base_path,
            "ServiceCount",
            len(config.mtp.services),
            ua.VariantType.UInt32,
            writable=False,
        )
        await self._add_variable(
            parent,
            base_path,
            "HealthStatus",
            "OK",
            ua.VariantType.String,
            writable=False,
        )
        await self._add_variable(
            parent,
            base_path,
            "LastError",
            "",
            ua.VariantType.String,
            writable=False,
        )


async def build_address_space(
    server: Server,
    config: GatewayConfig,
    namespace_idx: int,
    namespace_uri: str,
) -> tuple[
    dict[str, Node],
    dict[str, dict[str, Node]],
    dict[str, list[str]],
    dict[str, list[str]],
    dict[str, str],
    dict[str, str],
]:
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
        - Dictionary mapping source tags to Interlock node paths
        - Dictionary mapping tag names to bound node paths
        - Dictionary mapping tag names to tag node paths
        - Dictionary mapping writable node IDs to tag names
    """
    builder = MTPNodeBuilder(server, namespace_idx, namespace_uri)
    return await builder.build(config)
