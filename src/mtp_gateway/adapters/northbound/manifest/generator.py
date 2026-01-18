"""MTP Manifest Generator for AutomationML/CAEX format.

Generates MTP-compliant manifest files following VDI 2658 that can be
imported into Process Orchestration Layers (POLs).

The manifest describes:
- Module Type Package (MTP) structure
- Data Assemblies with OPC UA node references
- Services and their state machines
- Communication interfaces
"""

from __future__ import annotations

import uuid
import zipfile
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from xml.dom import minidom
from xml.etree import ElementTree as ET

import structlog

from mtp_gateway.adapters.northbound.node_ids import NodeIdStrategy

if TYPE_CHECKING:
    from pathlib import Path

    from mtp_gateway.config.schema import (
        DataAssemblyConfig,
        GatewayConfig,
        ServiceConfig,
    )

logger = structlog.get_logger(__name__)

# AutomationML/CAEX namespaces
CAEX_NS = "http://www.dke.de/CAEX"
MTP_NS = "http://www.2658.2/MTP"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

# VDI 2658 Role Classes
ROLE_CLASS_LIB = "MTPRoleClassLib"
INTERFACE_CLASS_LIB = "MTPInterfaceClassLib"


class MTPManifestGenerator:
    """Generator for MTP-compliant AutomationML manifests."""

    def __init__(self, config: GatewayConfig) -> None:
        """Initialize the generator.

        Args:
            config: Gateway configuration to generate manifest from
        """
        self._config = config
        self._pea_name = config.gateway.name
        self._namespace_uri = config.opcua.namespace_uri
        self._endpoint = config.opcua.endpoint
        self._node_ids = NodeIdStrategy(namespace_uri=self._namespace_uri, namespace_idx=0)

    def generate(self, output_path: Path | None = None) -> str:
        """Generate the MTP manifest XML.

        Args:
            output_path: Optional path to write the manifest

        Returns:
            XML string of the manifest
        """
        logger.info("Generating MTP manifest", pea_name=self._pea_name)

        # Create root CAEX element
        root = self._create_caex_root()

        # Add role class library reference
        self._add_role_class_lib(root)

        # Add interface class library reference
        self._add_interface_class_lib(root)

        # Add instance hierarchy (the actual module description)
        ih = self._add_instance_hierarchy(root)

        # Add PEA internal element
        pea_ie = self._add_pea_element(ih)

        # Add communication interface
        self._add_communication_interface(pea_ie)

        # Add data assemblies
        self._add_data_assemblies(pea_ie)

        # Add services
        self._add_services(pea_ie)

        # Generate XML string
        xml_str = self._to_xml_string(root)

        if output_path:
            output_path.write_text(xml_str, encoding="utf-8")
            logger.info("Manifest written", path=str(output_path))

        return xml_str

    def generate_package(self, output_path: Path) -> None:
        """Generate a complete MTP package (.mtp file).

        An MTP package is a ZIP file containing:
        - manifest.aml - The AutomationML manifest
        - Additional resources (icons, documentation)

        Args:
            output_path: Path for the .mtp output file
        """
        logger.info("Generating MTP package", path=str(output_path))

        # Generate manifest
        manifest_xml = self.generate()

        # Create ZIP package
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Add manifest
            zf.writestr("manifest.aml", manifest_xml)

            # Add package metadata
            metadata = self._generate_package_metadata()
            zf.writestr("manifest.info", metadata)

        logger.info("MTP package created", path=str(output_path))

    def _create_caex_root(self) -> ET.Element:
        """Create the root CAEXFile element."""
        # Register namespaces
        ET.register_namespace("", CAEX_NS)
        ET.register_namespace("xsi", XSI_NS)

        root = ET.Element(
            "CAEXFile",
            {
                "xmlns": CAEX_NS,
                f"{{{XSI_NS}}}schemaLocation": f"{CAEX_NS} CAEX_ClassModel_V.3.0.xsd",
                "FileName": f"{self._pea_name}_manifest.aml",
                "SchemaVersion": "3.0",
            },
        )

        # Add additional information
        ai = ET.SubElement(root, "AdditionalInformation")
        ET.SubElement(ai, "WriterHeader").text = "MTP Gateway Manifest Generator"
        ET.SubElement(ai, "WriterID").text = "mtp-gateway"
        vendor = self._config.gateway.vendor or self._config.gateway.name
        ET.SubElement(ai, "WriterVendor").text = vendor
        if self._config.gateway.vendor_url:
            ET.SubElement(ai, "WriterVendorURL").text = self._config.gateway.vendor_url
        ET.SubElement(ai, "WriterVersion").text = self._config.gateway.version
        ET.SubElement(ai, "LastWritingDateTime").text = datetime.now(UTC).isoformat()

        return root

    def _add_role_class_lib(self, root: ET.Element) -> None:
        """Add role class library reference."""
        rcl = ET.SubElement(
            root,
            "RoleClassLib",
            {"Name": ROLE_CLASS_LIB},
        )

        # Add MTP-specific role classes
        for role_name in [
            "ModuleTypePackage",
            "ProcessEquipmentAssembly",
            "Service",
            "DataAssembly",
            "CommunicationInterface",
        ]:
            ET.SubElement(rcl, "RoleClass", {"Name": role_name})

    def _add_interface_class_lib(self, root: ET.Element) -> None:
        """Add interface class library reference."""
        icl = ET.SubElement(
            root,
            "InterfaceClassLib",
            {"Name": INTERFACE_CLASS_LIB},
        )

        # Add OPC UA interface class
        ET.SubElement(icl, "InterfaceClass", {"Name": "OPCUAInterface"})

    def _add_instance_hierarchy(self, root: ET.Element) -> ET.Element:
        """Add the instance hierarchy."""
        return ET.SubElement(
            root,
            "InstanceHierarchy",
            {"Name": f"{self._pea_name}_Hierarchy"},
        )

    def _add_pea_element(self, parent: ET.Element) -> ET.Element:
        """Add the PEA (Process Equipment Assembly) internal element."""
        pea = ET.SubElement(
            parent,
            "InternalElement",
            {
                "Name": f"PEA_{self._pea_name}",
                "ID": self._generate_uuid(),
            },
        )

        # Add role requirement
        ET.SubElement(
            pea,
            "RoleRequirements",
            {"RefBaseRoleClassPath": f"{ROLE_CLASS_LIB}/ProcessEquipmentAssembly"},
        )

        # Add attributes
        self._add_attribute(pea, "Name", self._pea_name, "xs:string")
        self._add_attribute(pea, "Version", self._config.gateway.version, "xs:string")
        self._add_attribute(pea, "Description", self._config.gateway.description, "xs:string")

        return pea

    def _add_communication_interface(self, pea: ET.Element) -> None:
        """Add OPC UA communication interface."""
        comm = ET.SubElement(
            pea,
            "InternalElement",
            {
                "Name": "Communication",
                "ID": self._generate_uuid(),
            },
        )

        ET.SubElement(
            comm,
            "RoleRequirements",
            {"RefBaseRoleClassPath": f"{ROLE_CLASS_LIB}/CommunicationInterface"},
        )

        # Add OPC UA endpoint
        opcua = ET.SubElement(
            comm,
            "ExternalInterface",
            {
                "Name": "OPCUAServer",
                "ID": self._generate_uuid(),
                "RefBaseClassPath": f"{INTERFACE_CLASS_LIB}/OPCUAInterface",
            },
        )

        self._add_attribute(opcua, "Endpoint", self._endpoint, "xs:anyURI")
        self._add_attribute(opcua, "NamespaceURI", self._namespace_uri, "xs:anyURI")

    def _add_data_assemblies(self, pea: ET.Element) -> None:
        """Add data assembly elements."""
        da_container = ET.SubElement(
            pea,
            "InternalElement",
            {
                "Name": "DataAssemblies",
                "ID": self._generate_uuid(),
            },
        )

        for da_config in self._config.mtp.data_assemblies:
            self._add_data_assembly(da_container, da_config)

    def _add_data_assembly(self, parent: ET.Element, config: DataAssemblyConfig) -> None:
        """Add a single data assembly element."""
        da = ET.SubElement(
            parent,
            "InternalElement",
            {
                "Name": config.name,
                "ID": self._generate_uuid(),
            },
        )

        ET.SubElement(
            da,
            "RoleRequirements",
            {"RefBaseRoleClassPath": f"{ROLE_CLASS_LIB}/DataAssembly"},
        )

        # Add type attribute
        self._add_attribute(da, "Type", config.type, "xs:string")

        # Add description
        if config.description:
            self._add_attribute(da, "Description", config.description, "xs:string")

        # Add OPC UA node references for each binding
        base_node_path = f"PEA_{self._pea_name}.DataAssemblies.{config.name}"

        for attr_name, _tag_ref in config.bindings.items():
            node_id = self._node_ids.expanded_node_id(f"{base_node_path}.{attr_name}")
            self._add_opcua_reference(da, attr_name, node_id)

        # Add scaling attributes if present
        if config.v_scl_min is not None:
            self._add_attribute(da, "VSclMin", str(config.v_scl_min), "xs:double")
        if config.v_scl_max is not None:
            self._add_attribute(da, "VSclMax", str(config.v_scl_max), "xs:double")
        if config.v_unit is not None:
            self._add_attribute(da, "VUnit", str(config.v_unit), "xs:unsignedInt")

    def _add_services(self, pea: ET.Element) -> None:
        """Add service elements."""
        services_container = ET.SubElement(
            pea,
            "InternalElement",
            {
                "Name": "Services",
                "ID": self._generate_uuid(),
            },
        )

        for service_config in self._config.mtp.services:
            self._add_service(services_container, service_config)

    def _add_service(self, parent: ET.Element, config: ServiceConfig) -> None:
        """Add a single service element."""
        service = ET.SubElement(
            parent,
            "InternalElement",
            {
                "Name": config.name,
                "ID": self._generate_uuid(),
            },
        )

        ET.SubElement(
            service,
            "RoleRequirements",
            {"RefBaseRoleClassPath": f"{ROLE_CLASS_LIB}/Service"},
        )

        # Add mode attribute
        self._add_attribute(service, "ProxyMode", config.mode.value, "xs:string")

        # Add state machine variables
        base_node_path = f"PEA_{self._pea_name}.Services.{config.name}"

        self._add_opcua_reference(
            service,
            "CommandOp",
            self._node_ids.expanded_node_id(f"{base_node_path}.CommandOp"),
        )
        self._add_opcua_reference(
            service,
            "StateCur",
            self._node_ids.expanded_node_id(f"{base_node_path}.StateCur"),
        )
        self._add_opcua_reference(
            service,
            "ProcedureCur",
            self._node_ids.expanded_node_id(f"{base_node_path}.ProcedureCur"),
        )
        self._add_opcua_reference(
            service,
            "ProcedureReq",
            self._node_ids.expanded_node_id(f"{base_node_path}.ProcedureReq"),
        )

        # Add procedures
        if config.procedures:
            procs = ET.SubElement(
                service,
                "InternalElement",
                {
                    "Name": "Procedures",
                    "ID": self._generate_uuid(),
                },
            )

            for proc in config.procedures:
                proc_elem = ET.SubElement(
                    procs,
                    "InternalElement",
                    {
                        "Name": proc.name,
                        "ID": self._generate_uuid(),
                    },
                )
                self._add_attribute(proc_elem, "ProcedureId", str(proc.id), "xs:unsignedInt")
                self._add_attribute(
                    proc_elem,
                    "IsDefault",
                    str(proc.is_default).lower(),
                    "xs:boolean",
                )

        # Add parameters
        if config.parameters:
            params = ET.SubElement(
                service,
                "InternalElement",
                {
                    "Name": "Parameters",
                    "ID": self._generate_uuid(),
                },
            )

            for param in config.parameters:
                param_elem = ET.SubElement(
                    params,
                    "InternalElement",
                    {
                        "Name": param.name,
                        "ID": self._generate_uuid(),
                    },
                )
                self._add_attribute(param_elem, "DataAssembly", param.data_assembly, "xs:string")
                self._add_attribute(
                    param_elem,
                    "Required",
                    str(param.required).lower(),
                    "xs:boolean",
                )

    def _add_attribute(self, parent: ET.Element, name: str, value: str, datatype: str) -> None:
        """Add an attribute element."""
        attr = ET.SubElement(parent, "Attribute", {"Name": name, "AttributeDataType": datatype})
        ET.SubElement(attr, "Value").text = value

    def _add_opcua_reference(self, parent: ET.Element, name: str, node_id: str) -> None:
        """Add an OPC UA node reference attribute."""
        attr = ET.SubElement(
            parent,
            "Attribute",
            {"Name": f"{name}NodeId", "AttributeDataType": "xs:string"},
        )
        ET.SubElement(attr, "Value").text = node_id

    def _generate_uuid(self) -> str:
        """Generate a unique ID for CAEX elements."""
        return str(uuid.uuid4())

    def _to_xml_string(self, root: ET.Element) -> str:
        """Convert element tree to formatted XML string."""
        rough_string = ET.tostring(root, encoding="unicode")
        reparsed = minidom.parseString(rough_string)
        return reparsed.toprettyxml(indent="  ", encoding=None)

    def _generate_package_metadata(self) -> str:
        """Generate package metadata info."""
        return f"""MTP Package Information
Name: {self._pea_name}
Version: {self._config.gateway.version}
Generated: {datetime.now(UTC).isoformat()}
Generator: MTP Gateway
"""

    def get_all_node_ids(self) -> list[str]:
        """Get all OPC UA node IDs that will be in the manifest.

        This is useful for contract testing to ensure the manifest
        matches the server's address space.
        """
        node_ids: list[str] = []
        base = f"PEA_{self._pea_name}"

        # Data assembly nodes
        for da in self._config.mtp.data_assemblies:
            da_base = f"{base}.DataAssemblies.{da.name}"
            for attr_name in da.bindings:
                node_ids.append(self._node_ids.expanded_node_id(f"{da_base}.{attr_name}"))

        # Service nodes
        for service in self._config.mtp.services:
            svc_base = f"{base}.Services.{service.name}"
            node_ids.extend(
                [
                    self._node_ids.expanded_node_id(f"{svc_base}.CommandOp"),
                    self._node_ids.expanded_node_id(f"{svc_base}.StateCur"),
                    self._node_ids.expanded_node_id(f"{svc_base}.ProcedureCur"),
                    self._node_ids.expanded_node_id(f"{svc_base}.ProcedureReq"),
                ]
            )

        return node_ids


def generate_manifest(config: GatewayConfig, output_path: Path) -> None:
    """Convenience function to generate a manifest.

    Args:
        config: Gateway configuration
        output_path: Path to write the manifest
    """
    generator = MTPManifestGenerator(config)
    generator.generate(output_path)


def generate_package(config: GatewayConfig, output_path: Path) -> None:
    """Convenience function to generate an MTP package.

    Args:
        config: Gateway configuration
        output_path: Path to write the .mtp package
    """
    generator = MTPManifestGenerator(config)
    generator.generate_package(output_path)
