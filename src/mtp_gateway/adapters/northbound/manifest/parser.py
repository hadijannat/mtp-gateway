"""MTP Manifest Parser for AutomationML/CAEX format.

Parses MTP-compliant manifest files to extract:
- OPC UA node IDs
- Data assembly definitions
- Service definitions
- PEA (Process Equipment Assembly) information
"""

from __future__ import annotations

import defusedxml.ElementTree as ET
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from pathlib import Path

# AutomationML/CAEX namespace
CAEX_NS = "http://www.dke.de/CAEX"
NS = {"caex": CAEX_NS}

# Element tags with namespace prefix for querying
def _tag(name: str) -> str:
    """Create a namespaced tag."""
    return f"{{{CAEX_NS}}}{name}"

logger = structlog.get_logger(__name__)


class ManifestParser:
    """Parser for MTP AutomationML manifests."""

    def __init__(self, xml_content: str) -> None:
        """Initialize parser with XML content.

        Args:
            xml_content: The manifest XML as a string.
        """
        self._xml = xml_content
        self._root = ET.fromstring(xml_content)

    @classmethod
    def from_file(cls, path: Path) -> ManifestParser:
        """Create parser from a manifest file.

        Args:
            path: Path to the manifest file.

        Returns:
            ManifestParser instance.
        """
        content = path.read_text(encoding="utf-8")
        return cls(content)

    def extract_node_ids(self) -> set[str]:
        """Extract all OPC UA node IDs from the manifest.

        Returns:
            Set of OPC UA expanded node IDs.
        """
        node_ids: set[str] = set()

        # Find all attributes with NodeId suffix
        for attr in self._root.iter(_tag("Attribute")):
            name = attr.get("Name", "")
            if name.endswith("NodeId"):
                value_elem = attr.find(_tag("Value"))
                if value_elem is not None and value_elem.text:
                    node_ids.add(value_elem.text)

        logger.debug("Extracted node IDs", count=len(node_ids))
        return node_ids

    def extract_data_assemblies(self) -> list[dict[str, Any]]:
        """Extract data assembly definitions from the manifest.

        Returns:
            List of data assembly dictionaries with name, type, and node IDs.
        """
        data_assemblies: list[dict[str, Any]] = []

        # Find DataAssemblies container
        for ie in self._root.iter(_tag("InternalElement")):
            if ie.get("Name") == "DataAssemblies":
                # Each child InternalElement is a data assembly
                for da_elem in ie.findall(_tag("InternalElement")):
                    da = self._parse_data_assembly(da_elem)
                    if da:
                        data_assemblies.append(da)

        logger.debug("Extracted data assemblies", count=len(data_assemblies))
        return data_assemblies

    def _parse_data_assembly(self, elem: ET.Element) -> dict[str, Any] | None:
        """Parse a single data assembly element.

        Args:
            elem: The InternalElement representing the data assembly.

        Returns:
            Dictionary with data assembly info, or None if invalid.
        """
        name = elem.get("Name")
        if not name:
            return None

        da: dict[str, Any] = {
            "name": name,
            "id": elem.get("ID"),
            "type": None,
            "description": None,
            "node_ids": {},
        }

        # Extract attributes
        for attr in elem.findall(_tag("Attribute")):
            attr_name = attr.get("Name", "")
            value_elem = attr.find(_tag("Value"))
            value = value_elem.text if value_elem is not None else None

            if attr_name == "Type":
                da["type"] = value
            elif attr_name == "Description":
                da["description"] = value
            elif attr_name.endswith("NodeId"):
                # Extract the binding name (remove "NodeId" suffix)
                binding_name = attr_name[:-6]
                da["node_ids"][binding_name] = value

        return da

    def extract_services(self) -> list[dict[str, Any]]:
        """Extract service definitions from the manifest.

        Returns:
            List of service dictionaries with name, mode, and procedures.
        """
        services: list[dict[str, Any]] = []

        # Find Services container
        for ie in self._root.iter(_tag("InternalElement")):
            if ie.get("Name") == "Services":
                # Each child InternalElement is a service
                for svc_elem in ie.findall(_tag("InternalElement")):
                    svc = self._parse_service(svc_elem)
                    if svc:
                        services.append(svc)

        logger.debug("Extracted services", count=len(services))
        return services

    def _parse_service(self, elem: ET.Element) -> dict[str, Any] | None:
        """Parse a single service element.

        Args:
            elem: The InternalElement representing the service.

        Returns:
            Dictionary with service info, or None if invalid.
        """
        name = elem.get("Name")
        if not name:
            return None

        svc: dict[str, Any] = {
            "name": name,
            "id": elem.get("ID"),
            "mode": None,
            "node_ids": {},
            "procedures": [],
        }

        # Extract attributes
        for attr in elem.findall(_tag("Attribute")):
            attr_name = attr.get("Name", "")
            value_elem = attr.find(_tag("Value"))
            value = value_elem.text if value_elem is not None else None

            if attr_name == "ProxyMode":
                svc["mode"] = value
            elif attr_name.endswith("NodeId"):
                binding_name = attr_name[:-6]
                svc["node_ids"][binding_name] = value

        # Extract procedures - find child InternalElement named "Procedures"
        for child in elem.findall(_tag("InternalElement")):
            if child.get("Name") == "Procedures":
                for proc_elem in child.findall(_tag("InternalElement")):
                    proc = self._parse_procedure(proc_elem)
                    if proc:
                        svc["procedures"].append(proc)
                break

        return svc

    def _parse_procedure(self, elem: ET.Element) -> dict[str, Any] | None:
        """Parse a procedure element.

        Args:
            elem: The InternalElement representing the procedure.

        Returns:
            Dictionary with procedure info, or None if invalid.
        """
        name = elem.get("Name")
        if not name:
            return None

        proc: dict[str, Any] = {
            "name": name,
            "id": None,
            "is_default": False,
        }

        for attr in elem.findall(_tag("Attribute")):
            attr_name = attr.get("Name", "")
            value_elem = attr.find(_tag("Value"))
            value = value_elem.text if value_elem is not None else None

            if attr_name == "ProcedureId" and value:
                proc["id"] = int(value)
            elif attr_name == "IsDefault" and value:
                proc["is_default"] = value.lower() == "true"

        return proc

    def extract_pea_info(self) -> dict[str, Any]:
        """Extract PEA (Process Equipment Assembly) information.

        Returns:
            Dictionary with PEA name, version, and description.
        """
        pea_info: dict[str, Any] = {
            "name": None,
            "version": None,
            "description": None,
        }

        # Find PEA InternalElement (starts with "PEA_")
        for ie in self._root.iter(_tag("InternalElement")):
            name = ie.get("Name", "")
            if name.startswith("PEA_"):
                pea_info["pea_element_name"] = name

                # Extract attributes
                for attr in ie.findall(_tag("Attribute")):
                    attr_name = attr.get("Name", "")
                    value_elem = attr.find(_tag("Value"))
                    value = value_elem.text if value_elem is not None else None

                    if attr_name == "Name":
                        pea_info["name"] = value
                    elif attr_name == "Version":
                        pea_info["version"] = value
                    elif attr_name == "Description":
                        pea_info["description"] = value

                break  # Found the PEA element

        logger.debug("Extracted PEA info", name=pea_info.get("name"))
        return pea_info

    def extract_communication_info(self) -> dict[str, Any]:
        """Extract OPC UA communication interface information.

        Returns:
            Dictionary with endpoint and namespace URI.
        """
        comm_info: dict[str, Any] = {
            "endpoint": None,
            "namespace_uri": None,
        }

        # Find Communication InternalElement
        for ie in self._root.iter(_tag("InternalElement")):
            if ie.get("Name") == "Communication":
                # Find OPCUAServer external interface
                for ext in ie.iter(_tag("ExternalInterface")):
                    if ext.get("Name") == "OPCUAServer":
                        for attr in ext.findall(_tag("Attribute")):
                            attr_name = attr.get("Name", "")
                            value_elem = attr.find(_tag("Value"))
                            value = value_elem.text if value_elem is not None else None

                            if attr_name == "Endpoint":
                                comm_info["endpoint"] = value
                            elif attr_name == "NamespaceURI":
                                comm_info["namespace_uri"] = value
                break

        return comm_info


__all__ = ["ManifestParser"]
