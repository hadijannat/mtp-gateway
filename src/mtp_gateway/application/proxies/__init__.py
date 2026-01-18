"""Service proxy adapters for different proxy modes.

Provides THIN, THICK, and HYBRID proxy implementations for
routing service commands based on configuration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mtp_gateway.application.proxies.base import ProxyResult, ServiceProxy
from mtp_gateway.application.proxies.hybrid import HybridProxy
from mtp_gateway.application.proxies.thick import ThickProxy
from mtp_gateway.application.proxies.thin import ThinProxy
from mtp_gateway.config.schema import ProxyMode

if TYPE_CHECKING:
    from mtp_gateway.application.tag_manager import TagManager
    from mtp_gateway.config.schema import ServiceConfig


def create_proxy(
    config: ServiceConfig,
    tag_manager: TagManager,
) -> ServiceProxy:
    """Create the appropriate proxy for a service configuration.

    Factory function that returns the correct proxy implementation
    based on the service's proxy mode.

    Args:
        config: Service configuration with proxy mode.
        tag_manager: TagManager for reading/writing tags.

    Returns:
        ServiceProxy implementation for the configured mode.

    Raises:
        ValueError: If proxy mode is not recognized.
    """
    match config.mode:
        case ProxyMode.THICK:
            return ThickProxy(config, tag_manager)
        case ProxyMode.THIN:
            return ThinProxy(config, tag_manager)
        case ProxyMode.HYBRID:
            return HybridProxy(config, tag_manager)
        case _:
            raise ValueError(f"Unknown proxy mode: {config.mode}")


__all__ = [
    "HybridProxy",
    "ProxyResult",
    "ServiceProxy",
    "ThickProxy",
    "ThinProxy",
    "create_proxy",
]
