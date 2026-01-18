"""NodeId helpers shared by OPC UA server and manifest generator.

Provides deterministic node path generation and stable NodeId strings
using namespace URIs (nsu=) so manifests stay valid across restarts.
"""

from __future__ import annotations

from dataclasses import dataclass

from asyncua import ua


@dataclass(frozen=True)
class NodeIdStrategy:
    """Deterministic NodeId strategy for MTP address space."""

    namespace_uri: str
    namespace_idx: int

    def path(self, *parts: str) -> str:
        """Join node path parts into a dot-separated identifier."""
        return ".".join(part for part in parts if part)

    def ua_node_id(self, path: str) -> ua.NodeId:
        """Create a NodeId for server creation with namespace index."""
        return ua.NodeId(path, self.namespace_idx)

    def expanded_node_id(self, path: str) -> str:
        """Create an ExpandedNodeId string using namespace URI.

        Example: nsu=urn:example:mtp;s=PEA_Module.DataAssemblies.Temp.V
        """
        return f"nsu={self.namespace_uri};s={path}"
