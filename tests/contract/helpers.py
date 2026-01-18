"""Helper classes for contract testing.

These classes extract and compare node information between the
generated manifest and the live OPC UA server.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import defusedxml.ElementTree as ET
from asyncua import ua

if TYPE_CHECKING:
    from asyncua import Client, Node

    from mtp_gateway.config.schema import GatewayConfig


@dataclass
class ContractViolation:
    """Details about a contract violation between manifest and server."""

    node_id: str
    violation_type: str
    expected: str | None = None
    actual: str | None = None
    details: str = ""

    def __str__(self) -> str:
        msg = f"{self.violation_type}: {self.node_id}"
        if self.expected:
            msg += f"\n  Expected: {self.expected}"
        if self.actual:
            msg += f"\n  Actual: {self.actual}"
        if self.details:
            msg += f"\n  Details: {self.details}"
        return msg


@dataclass
class ManifestNodeInfo:
    """Information about a node extracted from the manifest."""

    node_id: str
    name: str
    parent_path: str
    data_type: str | None = None
    attributes: dict[str, str] = field(default_factory=dict)


class ManifestParser:
    """Parser for MTP AutomationML manifests.

    Extracts node IDs and their metadata from the generated
    manifest XML for comparison with the live server.
    """

    # Namespaces used in AutomationML
    CAEX_NS = "http://www.dke.de/CAEX"
    CAEX_NS_PREFIX = f"{{{CAEX_NS}}}"

    def __init__(self, manifest_xml: str) -> None:
        """Initialize parser with manifest XML content.

        Args:
            manifest_xml: The AutomationML manifest XML string
        """
        self._xml = manifest_xml
        self._root = ET.fromstring(manifest_xml)
        self._nodes: list[ManifestNodeInfo] = []
        self._parse()

    def _is_internal_element(self, tag: str) -> bool:
        """Check if tag represents an InternalElement (with or without namespace)."""
        return tag in ("InternalElement", f"{self.CAEX_NS_PREFIX}InternalElement")

    def _is_attribute(self, tag: str) -> bool:
        """Check if tag represents an Attribute (with or without namespace)."""
        return tag in ("Attribute", f"{self.CAEX_NS_PREFIX}Attribute")

    def _is_value(self, tag: str) -> bool:
        """Check if tag represents a Value (with or without namespace)."""
        return tag in ("Value", f"{self.CAEX_NS_PREFIX}Value")

    def _parse(self) -> None:
        """Parse the manifest and extract all node references."""
        # Find all InternalElements
        for elem in self._root.iter():
            if self._is_internal_element(elem.tag):
                self._parse_internal_element(elem, "")

    def _parse_internal_element(self, elem: ET.Element, parent_path: str) -> None:
        """Parse an InternalElement and its children."""
        name = elem.get("Name", "")
        current_path = f"{parent_path}.{name}" if parent_path else name

        # Find node ID attributes (ending in NodeId)
        for child in elem:
            if self._is_attribute(child.tag):
                attr_name = child.get("Name", "")
                if attr_name.endswith("NodeId"):
                    # Find Value child
                    for value_child in child:
                        if self._is_value(value_child.tag) and value_child.text:
                            node_id = value_child.text.strip()
                            self._nodes.append(
                                ManifestNodeInfo(
                                    node_id=node_id,
                                    name=attr_name.replace("NodeId", ""),
                                    parent_path=current_path,
                                )
                            )
                            break

        # Recursively parse child elements
        for child in elem:
            if self._is_internal_element(child.tag):
                self._parse_internal_element(child, current_path)

    def get_all_node_ids(self) -> set[str]:
        """Get all OPC UA node IDs referenced in the manifest.

        Returns:
            Set of expanded node ID strings
        """
        return {node.node_id for node in self._nodes}

    def get_nodes(self) -> list[ManifestNodeInfo]:
        """Get all parsed node information.

        Returns:
            List of ManifestNodeInfo objects
        """
        return self._nodes.copy()

    def get_node_ids_by_pattern(self, pattern: str) -> set[str]:
        """Get node IDs matching a regex pattern.

        Args:
            pattern: Regex pattern to match against node IDs

        Returns:
            Set of matching node ID strings
        """
        regex = re.compile(pattern)
        return {node.node_id for node in self._nodes if regex.search(node.node_id)}


class OPCUABrowser:
    """Browser for OPC UA server address space.

    Traverses the server's address space to collect node information
    for contract verification.
    """

    def __init__(self, client: Client, config: GatewayConfig) -> None:
        """Initialize browser.

        Args:
            client: Connected OPC UA client
            config: Gateway configuration for namespace info
        """
        self._client = client
        self._config = config
        self._pea_name = f"PEA_{config.gateway.name}"

    async def browse_all_node_ids(self) -> set[str]:
        """Browse and collect all node IDs under the PEA namespace.

        Returns:
            Set of expanded node ID strings
        """
        node_ids: set[str] = set()
        namespace_uri = self._config.opcua.namespace_uri

        # Get namespace index
        ns_array = await self._client.get_namespace_array()
        try:
            ns_idx = ns_array.index(namespace_uri)
        except ValueError:
            # Namespace not found
            return node_ids

        # Start from Objects folder
        objects = self._client.get_objects_node()

        # Find PEA node
        pea_node = await self._find_child_by_name(objects, self._pea_name)
        if pea_node is None:
            return node_ids

        # Recursively browse
        await self._browse_recursive(pea_node, node_ids, ns_idx)

        return node_ids

    async def browse_nodes_with_types(self) -> dict[str, str]:
        """Browse and collect node IDs with their data types.

        Returns:
            Dict mapping node ID strings to their VariantType names
        """
        result: dict[str, str] = {}
        namespace_uri = self._config.opcua.namespace_uri

        # Get namespace index
        ns_array = await self._client.get_namespace_array()
        try:
            ns_idx = ns_array.index(namespace_uri)
        except ValueError:
            return result

        # Start from Objects folder
        objects = self._client.get_objects_node()

        # Find PEA node
        pea_node = await self._find_child_by_name(objects, self._pea_name)
        if pea_node is None:
            return result

        # Recursively browse with types
        await self._browse_recursive_with_types(pea_node, result, ns_idx)

        return result

    async def _find_child_by_name(self, parent: Node, name: str) -> Node | None:
        """Find a child node by its browse name."""
        children = await parent.get_children()
        for child in children:
            browse_name = await child.read_browse_name()
            if browse_name.Name == name:
                return child
        return None

    async def _browse_recursive(
        self,
        node: Node,
        node_ids: set[str],
        ns_idx: int,
    ) -> None:
        """Recursively browse and collect node IDs."""
        # Get node's NodeId
        nodeid = node.nodeid

        # Only collect nodes from our namespace
        if nodeid.NamespaceIndex == ns_idx:
            # Build expanded node ID string
            expanded = f"nsu={self._config.opcua.namespace_uri};s={nodeid.Identifier}"
            node_ids.add(expanded)

        # Browse children
        try:
            children = await node.get_children()
            for child in children:
                await self._browse_recursive(child, node_ids, ns_idx)
        except Exception:
            # Some nodes may not have browsable children
            pass

    async def _browse_recursive_with_types(
        self,
        node: Node,
        result: dict[str, str],
        ns_idx: int,
    ) -> None:
        """Recursively browse and collect node IDs with types."""
        nodeid = node.nodeid

        if nodeid.NamespaceIndex == ns_idx:
            expanded = f"nsu={self._config.opcua.namespace_uri};s={nodeid.Identifier}"

            # Try to get data type
            try:
                node_class = await node.read_node_class()
                if node_class == ua.NodeClass.Variable:
                    data_type = await node.read_data_type()
                    # Get the data type name
                    data_type_node = self._client.get_node(data_type)
                    data_type_name = await data_type_node.read_browse_name()
                    result[expanded] = data_type_name.Name
                else:
                    result[expanded] = "Object"
            except Exception:
                result[expanded] = "Unknown"

        # Browse children
        try:
            children = await node.get_children()
            for child in children:
                await self._browse_recursive_with_types(child, result, ns_idx)
        except Exception:
            pass

    async def get_node_value(self, node_id_str: str) -> Any:
        """Read a value from a node by its string NodeId.

        Args:
            node_id_str: Expanded node ID string

        Returns:
            The node's value
        """
        # Parse the node ID string format: nsu=namespace;s=identifier
        match = re.match(r"nsu=([^;]+);s=(.+)", node_id_str)
        if not match:
            raise ValueError(f"Invalid node ID format: {node_id_str}")

        namespace_uri, identifier = match.groups()

        # Get namespace index
        ns_array = await self._client.get_namespace_array()
        ns_idx = ns_array.index(namespace_uri)

        # Get the node
        nodeid = ua.NodeId(identifier, ns_idx)
        node = self._client.get_node(nodeid)

        return await node.read_value()

    async def verify_node_exists(self, node_id_str: str) -> bool:
        """Check if a node exists in the server.

        Args:
            node_id_str: Expanded node ID string

        Returns:
            True if node exists, False otherwise
        """
        try:
            match = re.match(r"nsu=([^;]+);s=(.+)", node_id_str)
            if not match:
                return False

            namespace_uri, identifier = match.groups()
            ns_array = await self._client.get_namespace_array()

            try:
                ns_idx = ns_array.index(namespace_uri)
            except ValueError:
                return False

            nodeid = ua.NodeId(identifier, ns_idx)
            node = self._client.get_node(nodeid)

            # Try to read the node class - will fail if node doesn't exist
            await node.read_node_class()
            return True

        except Exception:
            return False


def compare_manifest_to_server(
    manifest_node_ids: set[str],
    server_node_ids: set[str],
) -> list[ContractViolation]:
    """Compare manifest node IDs against server node IDs.

    Args:
        manifest_node_ids: Node IDs from the manifest
        server_node_ids: Node IDs from the server

    Returns:
        List of contract violations found
    """
    violations: list[ContractViolation] = []

    # Check for manifest nodes missing from server
    missing_in_server = manifest_node_ids - server_node_ids
    for node_id in missing_in_server:
        violations.append(
            ContractViolation(
                node_id=node_id,
                violation_type="MISSING_IN_SERVER",
                details="Node referenced in manifest does not exist in server",
            )
        )

    return violations


def compare_data_types(
    manifest_types: dict[str, str],
    server_types: dict[str, str],
) -> list[ContractViolation]:
    """Compare data types between manifest and server.

    Args:
        manifest_types: Dict mapping node IDs to expected types
        server_types: Dict mapping node IDs to actual types

    Returns:
        List of type mismatch violations
    """
    violations: list[ContractViolation] = []

    for node_id, expected_type in manifest_types.items():
        if node_id in server_types:
            actual_type = server_types[node_id]
            if expected_type != actual_type:
                violations.append(
                    ContractViolation(
                        node_id=node_id,
                        violation_type="TYPE_MISMATCH",
                        expected=expected_type,
                        actual=actual_type,
                    )
                )

    return violations
