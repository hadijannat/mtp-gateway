"""MTP Gateway - Bridging legacy PLCs to MTP-compliant OPC UA interface.

This package provides a production-grade gateway that:
- Connects to brownfield PLCs via Modbus, S7, EtherNet/IP, or OPC UA
- Exposes an MTP-compliant OPC UA address space (VDI/VDE/NAMUR 2658)
- Generates AutomationML manifests for POL import
- Supports Thin, Thick, and Hybrid proxy modes
"""

# Version is set dynamically by hatch-vcs from git tags
try:
    from mtp_gateway._version import __version__
except ImportError:
    __version__ = "0.0.0.dev0"  # Development fallback

__author__ = "MTP Gateway Team"

from mtp_gateway.domain.model.tags import Quality, TagValue

__all__ = [
    "Quality",
    "TagValue",
    "__version__",
]
