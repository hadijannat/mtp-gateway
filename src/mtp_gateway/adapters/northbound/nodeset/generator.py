"""OPC UA NodeSet2 XML Generator for MTP Gateway.

Generates OPC UA NodeSet2 XML files that describe the MTP address space.
These files can be imported by other OPC UA servers/tools for interoperability.

The NodeSet2 format follows the OPC Foundation specification:
https://opcfoundation.org/UA/schemas/

Structure matches the gateway's OPC UA server address space:
- Root/Objects/PEA_{Name}/
    - DataAssemblies/
    - Services/
"""

from __future__ import annotations

import xml.etree.ElementTree as ET  # nosec B405 - generation only, no parsing
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from mtp_gateway.adapters.northbound.node_ids import NodeIdStrategy
from mtp_gateway.config.schema import DataTypeConfig

if TYPE_CHECKING:
    from pathlib import Path

    from mtp_gateway.config.schema import (
        DataAssemblyConfig,
        GatewayConfig,
        ServiceConfig,
        TagConfig,
    )

logger = structlog.get_logger(__name__)

# OPC UA NodeSet2 namespace
NODESET_NS = "http://opcfoundation.org/UA/2011/03/UANodeSet.xsd"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
UA_NS = "http://opcfoundation.org/UA/"

# OPC UA standard NodeIds
OPC_BASE_OBJECT_TYPE = "i=58"  # BaseObjectType
OPC_FOLDER_TYPE = "i=61"  # FolderType
OPC_HAS_TYPE_DEFINITION = "i=40"  # HasTypeDefinition
OPC_ORGANIZES = "i=35"  # Organizes
OPC_HAS_COMPONENT = "i=47"  # HasComponent
OPC_OBJECTS_FOLDER = "i=85"  # Objects folder

# DataType NodeIds
DATATYPE_MAP = {
    DataTypeConfig.BOOL: ("i=1", "Boolean"),
    DataTypeConfig.INT16: ("i=4", "Int16"),
    DataTypeConfig.INT32: ("i=6", "Int32"),
    DataTypeConfig.INT64: ("i=8", "Int64"),
    DataTypeConfig.UINT16: ("i=5", "UInt16"),
    DataTypeConfig.UINT32: ("i=7", "UInt32"),
    DataTypeConfig.UINT64: ("i=9", "UInt64"),
    DataTypeConfig.FLOAT32: ("i=10", "Float"),
    DataTypeConfig.FLOAT64: ("i=11", "Double"),
    DataTypeConfig.STRING: ("i=12", "String"),
}


class NodeSetGenerator:
    """Generator for OPC UA NodeSet2 XML files.

    Creates a NodeSet2 XML file that describes the MTP address space,
    suitable for import into other OPC UA tools/servers.
    """

    def __init__(self, config: GatewayConfig, deterministic: bool = False) -> None:
        """Initialize the generator.

        Args:
            config: Gateway configuration to generate NodeSet from.
            deterministic: If True, use fixed timestamp for reproducibility.
        """
        self._config = config
        self._pea_name = config.gateway.name
        self._namespace_uri = config.opcua.namespace_uri
        self._node_ids = NodeIdStrategy(namespace_uri=self._namespace_uri, namespace_idx=1)
        self._deterministic = deterministic

    def generate(self, output_path: Path | None = None) -> str:
        """Generate the NodeSet2 XML.

        Args:
            output_path: Optional path to write the XML file.

        Returns:
            XML string of the NodeSet.
        """
        logger.info("Generating NodeSet2 XML", pea_name=self._pea_name)

        # Create root UANodeSet element
        root = self._create_root()

        # Add namespace URIs
        self._add_namespaces(root)

        # Add type aliases
        self._add_aliases(root)

        # Add PEA root folder
        pea_path = f"PEA_{self._pea_name}"
        self._add_folder(root, pea_path, "PEA_" + self._pea_name, OPC_OBJECTS_FOLDER)

        # Add main folders
        da_path = f"{pea_path}.DataAssemblies"
        self._add_folder(root, da_path, "DataAssemblies", f"ns=1;s={pea_path}")

        services_path = f"{pea_path}.Services"
        self._add_folder(root, services_path, "Services", f"ns=1;s={pea_path}")

        # Add data assemblies
        tag_lookup = {tag.name: tag for tag in self._config.tags}
        for da_config in self._config.mtp.data_assemblies:
            self._add_data_assembly(root, pea_path, da_config, tag_lookup)

        # Add services
        for service_config in self._config.mtp.services:
            self._add_service(root, pea_path, service_config)

        # Generate XML string
        xml_str = self._to_xml_string(root)

        if output_path:
            output_path.write_text(xml_str, encoding="utf-8")
            logger.info("NodeSet2 XML written", path=str(output_path))

        return xml_str

    def _create_root(self) -> ET.Element:
        """Create the root UANodeSet element."""
        ET.register_namespace("", NODESET_NS)
        ET.register_namespace("xsi", XSI_NS)
        ET.register_namespace("uax", UA_NS)

        root = ET.Element(
            "UANodeSet",
            {
                "xmlns": NODESET_NS,
                f"{{{XSI_NS}}}schemaLocation": f"{NODESET_NS} UANodeSet.xsd",
            },
        )

        # Add modification timestamp
        timestamp = self._get_timestamp()
        root.set("LastModified", timestamp)

        return root

    def _add_namespaces(self, root: ET.Element) -> None:
        """Add namespace URIs section."""
        ns_uris = ET.SubElement(root, "NamespaceUris")
        uri = ET.SubElement(ns_uris, "Uri")
        uri.text = self._namespace_uri

    def _add_aliases(self, root: ET.Element) -> None:
        """Add type aliases for common data types."""
        aliases = ET.SubElement(root, "Aliases")

        # Add standard type aliases
        alias_list = [
            ("Boolean", "i=1"),
            ("Int16", "i=4"),
            ("UInt16", "i=5"),
            ("Int32", "i=6"),
            ("UInt32", "i=7"),
            ("Int64", "i=8"),
            ("UInt64", "i=9"),
            ("Float", "i=10"),
            ("Double", "i=11"),
            ("String", "i=12"),
            ("FolderType", "i=61"),
            ("Organizes", "i=35"),
            ("HasTypeDefinition", "i=40"),
            ("HasComponent", "i=47"),
        ]

        for alias_name, alias_value in alias_list:
            alias = ET.SubElement(aliases, "Alias", {"Alias": alias_name})
            alias.text = alias_value

    def _add_folder(
        self, root: ET.Element, node_path: str, display_name: str, parent_node_id: str
    ) -> None:
        """Add a folder node."""
        obj = ET.SubElement(
            root,
            "UAObject",
            {
                "NodeId": f"ns=1;s={node_path}",
                "BrowseName": f"1:{display_name}",
            },
        )

        dn = ET.SubElement(obj, "DisplayName")
        dn.text = display_name

        refs = ET.SubElement(obj, "References")

        # HasTypeDefinition -> FolderType
        ref_type = ET.SubElement(refs, "Reference", {"ReferenceType": "HasTypeDefinition"})
        ref_type.text = OPC_FOLDER_TYPE

        # Inverse reference to parent
        ref_parent = ET.SubElement(
            refs, "Reference", {"ReferenceType": "Organizes", "IsForward": "false"}
        )
        ref_parent.text = parent_node_id

    def _add_data_assembly(
        self,
        root: ET.Element,
        pea_path: str,
        da_config: DataAssemblyConfig,
        tag_lookup: dict[str, TagConfig],
    ) -> None:
        """Add a data assembly and its variables."""
        da_path = f"{pea_path}.DataAssemblies.{da_config.name}"

        # Add DA folder
        self._add_folder(root, da_path, da_config.name, f"ns=1;s={pea_path}.DataAssemblies")

        # Add variables for each binding
        for attr_name, tag_ref in da_config.bindings.items():
            tag_config = tag_lookup.get(tag_ref)
            if tag_config:
                var_path = f"{da_path}.{attr_name}"
                self._add_variable(root, var_path, attr_name, da_path, tag_config.datatype)

    def _add_service(
        self, root: ET.Element, pea_path: str, service_config: ServiceConfig
    ) -> None:
        """Add a service and its state machine variables."""
        svc_path = f"{pea_path}.Services.{service_config.name}"

        # Add service folder
        self._add_folder(root, svc_path, service_config.name, f"ns=1;s={pea_path}.Services")

        # Add standard MTP service variables
        # CommandOp - writable UInt32 for command input
        self._add_variable(
            root, f"{svc_path}.CommandOp", "CommandOp", svc_path, DataTypeConfig.UINT32
        )

        # StateCur - readable UInt32 for current state
        self._add_variable(
            root, f"{svc_path}.StateCur", "StateCur", svc_path, DataTypeConfig.UINT32
        )

        # ProcedureCur - readable UInt32 for current procedure
        self._add_variable(
            root, f"{svc_path}.ProcedureCur", "ProcedureCur", svc_path, DataTypeConfig.UINT32
        )

        # ProcedureReq - writable UInt32 for requested procedure
        self._add_variable(
            root, f"{svc_path}.ProcedureReq", "ProcedureReq", svc_path, DataTypeConfig.UINT32
        )

    def _add_variable(
        self,
        root: ET.Element,
        node_path: str,
        display_name: str,
        parent_path: str,
        datatype: DataTypeConfig,
    ) -> None:
        """Add a variable node."""
        _datatype_id, datatype_alias = DATATYPE_MAP.get(datatype, ("i=12", "String"))

        var = ET.SubElement(
            root,
            "UAVariable",
            {
                "NodeId": f"ns=1;s={node_path}",
                "BrowseName": f"1:{display_name}",
                "DataType": datatype_alias,
                "AccessLevel": "3",  # Read + Write
            },
        )

        dn = ET.SubElement(var, "DisplayName")
        dn.text = display_name

        refs = ET.SubElement(var, "References")

        # Inverse reference to parent
        ref_parent = ET.SubElement(
            refs, "Reference", {"ReferenceType": "HasComponent", "IsForward": "false"}
        )
        ref_parent.text = f"ns=1;s={parent_path}"

    def _get_timestamp(self) -> str:
        """Get timestamp for NodeSet metadata."""
        if self._deterministic:
            return "2000-01-01T00:00:00Z"
        return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _to_xml_string(self, root: ET.Element) -> str:
        """Convert element tree to formatted XML string."""
        if hasattr(ET, "indent"):
            ET.indent(root, space="  ")
        else:
            self._indent_element(root)

        # Add XML declaration
        return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(
            root, encoding="unicode"
        )

    def _indent_element(self, elem: ET.Element, level: int = 0) -> None:
        """Indent XML elements for readability."""
        indent = "\n" + level * "  "
        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = indent + "  "
            for child in elem:
                self._indent_element(child, level + 1)
            if not elem[-1].tail or not elem[-1].tail.strip():
                elem[-1].tail = indent
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = indent


def generate_nodeset(config: GatewayConfig, output_path: Path) -> None:
    """Convenience function to generate a NodeSet2 XML file.

    Args:
        config: Gateway configuration.
        output_path: Path to write the NodeSet2 XML file.
    """
    generator = NodeSetGenerator(config)
    generator.generate(output_path)
