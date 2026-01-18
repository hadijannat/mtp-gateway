"""OPC UA Client connector using asyncua.

Implements communication with external OPC UA servers as a southbound data source.
Unlike memory-based protocols (Modbus, S7, EIP), OPC UA uses NodeId addressing.

OPC UA NodeId Formats:
- ns=2;i=1001          - Numeric ID 1001 in namespace 2
- ns=2;s=Temperature   - String ID "Temperature" in namespace 2
- ns=2;g=550e8400-...  - GUID-based NodeId
- ns=0;i=2258          - Well-known node (ServerState)
- i=2258               - Default namespace (0), numeric ID
- s=MyTag              - Default namespace (0), string ID

Configuration example:
    tags:
      - name: remote_temperature
        connector: opc_ua_server
        address: "ns=2;i=1001"
        datatype: float32
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from mtp_gateway.adapters.southbound.base import BaseConnector
from mtp_gateway.config.schema import SecurityPolicy
from mtp_gateway.domain.model.tags import Quality, TagValue

if TYPE_CHECKING:
    from mtp_gateway.config.schema import OPCUAClientConnectorConfig

# Import asyncua - required dependency
from asyncua import Client, ua

logger = structlog.get_logger(__name__)


# Regular expressions for parsing NodeId strings
# Format: ns=N;type=identifier or type=identifier (default ns=0)
_NS_PATTERN = re.compile(r"^ns=(\d+);(.+)$", re.IGNORECASE)
_NUMERIC_PATTERN = re.compile(r"^i=(\d+)$", re.IGNORECASE)
_STRING_PATTERN = re.compile(r"^s=(.+)$", re.IGNORECASE)
_GUID_PATTERN = re.compile(
    r"^g=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
    re.IGNORECASE,
)


def parse_node_id(address: str) -> ua.NodeId:
    """Parse OPC UA NodeId string to asyncua NodeId object.

    Supports formats:
    - "ns=2;i=1001"          - Numeric ID in namespace 2
    - "ns=2;s=Temperature"   - String ID in namespace 2
    - "ns=2;g=550e8400-..."  - GUID ID in namespace 2
    - "i=2258"               - Numeric ID in default namespace (0)
    - "s=MyTag"              - String ID in default namespace (0)

    Args:
        address: NodeId string in OPC UA format

    Returns:
        asyncua NodeId object

    Raises:
        ValueError: If address format is invalid
    """
    address = address.strip()

    if not address:
        raise ValueError("Invalid NodeId: empty string")

    # Extract namespace if present
    namespace = 0
    identifier_part = address

    ns_match = _NS_PATTERN.match(address)
    if ns_match:
        namespace = int(ns_match.group(1))
        identifier_part = ns_match.group(2)

    # Parse identifier based on type prefix
    # Numeric: i=N
    numeric_match = _NUMERIC_PATTERN.match(identifier_part)
    if numeric_match:
        numeric_id = int(numeric_match.group(1))
        return ua.NodeId(numeric_id, namespace)

    # String: s=text
    string_match = _STRING_PATTERN.match(identifier_part)
    if string_match:
        string_id = string_match.group(1)
        return ua.NodeId(string_id, namespace)

    # GUID: g=uuid
    guid_match = _GUID_PATTERN.match(identifier_part)
    if guid_match:
        guid_id = UUID(guid_match.group(1))
        return ua.NodeId(guid_id, namespace)

    raise ValueError(f"Invalid NodeId format: '{address}'")


def _status_code_to_quality(status_code: Any) -> Quality:
    """Map OPC UA StatusCode to Quality enum.

    Args:
        status_code: asyncua StatusCode object

    Returns:
        Quality enum value
    """
    if status_code.is_good():
        return Quality.GOOD

    # Check for specific bad status codes
    status_name = getattr(status_code, "name", "")

    if status_code.is_bad():
        if "NodeIdUnknown" in status_name:
            return Quality.BAD_CONFIG_ERROR
        if "NotConnected" in status_name:
            return Quality.BAD_NO_COMMUNICATION
        return Quality.BAD

    # Uncertain status
    return Quality.UNCERTAIN


class OPCUAClientConnector(BaseConnector):
    """OPC UA client connector using asyncua.

    Connects to external OPC UA servers as a southbound data source.
    asyncua is async-native, so no thread wrapping is needed.

    Security policies and user authentication are supported.
    """

    def __init__(self, config: OPCUAClientConnectorConfig) -> None:
        """Initialize OPC UA client connector.

        Args:
            config: OPC UA client connector configuration
        """
        super().__init__(config)
        self._client: Client | None = None
        self._endpoint = config.endpoint
        self._security_policy = config.security_policy
        self._username = config.username
        self._password = config.password
        self._cert_path = config.cert_path
        self._key_path = config.key_path

    async def _do_connect(self) -> None:
        """Connect to OPC UA server.

        Creates asyncua Client, applies security and credentials, then connects.
        """
        self._client = Client(url=self._endpoint)

        # Set username/password if provided
        if self._username:
            self._client.set_user(self._username)
        if self._password:
            self._client.set_password(self._password)

        # Apply security policy if not None
        if self._security_policy and self._security_policy != SecurityPolicy.NONE:
            # Security requires certificate and key paths
            if self._cert_path and self._key_path:
                # Map security policy to asyncua security string
                policy_map = {
                    SecurityPolicy.BASIC128RSA15_SIGN: "Basic128Rsa15,Sign",
                    SecurityPolicy.BASIC128RSA15_SIGN_ENCRYPT: "Basic128Rsa15,SignAndEncrypt",
                    SecurityPolicy.BASIC256_SIGN: "Basic256,Sign",
                    SecurityPolicy.BASIC256_SIGN_ENCRYPT: "Basic256,SignAndEncrypt",
                    SecurityPolicy.BASIC256SHA256_SIGN: "Basic256Sha256,Sign",
                    SecurityPolicy.BASIC256SHA256_SIGN_ENCRYPT: "Basic256Sha256,SignAndEncrypt",
                }
                security_string = policy_map.get(self._security_policy)
                if security_string:
                    await self._client.set_security_string(
                        f"{security_string},{self._cert_path},{self._key_path}"
                    )

        await self._client.connect()

        logger.debug(
            "OPC UA client connected",
            endpoint=self._endpoint,
        )

    async def _do_disconnect(self) -> None:
        """Disconnect from OPC UA server."""
        if self._client:
            await self._client.disconnect()
            self._client = None

    async def read_tags(self, addresses: list[str]) -> dict[str, TagValue]:
        """Read tags with OPC UA per-value quality handling.

        Overrides BaseConnector.read_tags() to properly map OPC UA
        StatusCodes to Quality enum per-value.

        Args:
            addresses: List of NodeId address strings to read

        Returns:
            Dictionary mapping addresses to TagValue instances
        """
        if not addresses:
            return {}

        self._health.total_reads += len(addresses)

        if not self._client:
            # Not connected - return bad quality
            now = datetime.now(timezone.utc)
            self._health.record_error("Not connected")
            return {
                addr: TagValue(
                    value=0,
                    timestamp=now,
                    quality=Quality.BAD_NO_COMMUNICATION,
                )
                for addr in addresses
            }

        try:
            # Parse NodeIds and get nodes
            nodes = []
            valid_addresses = []

            for addr in addresses:
                try:
                    node_id = parse_node_id(addr)
                    node = self._client.get_node(node_id)
                    nodes.append(node)
                    valid_addresses.append(addr)
                except ValueError as e:
                    logger.warning(
                        "Failed to parse NodeId",
                        address=addr,
                        error=str(e),
                    )

            if not nodes:
                now = datetime.now(timezone.utc)
                return {
                    addr: TagValue(
                        value=0,
                        timestamp=now,
                        quality=Quality.BAD_CONFIG_ERROR,
                    )
                    for addr in addresses
                }

            # Batch read all nodes
            data_values = await self._client.read_values(nodes)
            self._health.record_success()

            # Process results with per-value quality
            result: dict[str, TagValue] = {}
            now = datetime.now(timezone.utc)

            for addr, dv in zip(valid_addresses, data_values):
                quality = _status_code_to_quality(dv.StatusCode)
                value = dv.Value.Value if dv.Value is not None else 0

                result[addr] = TagValue(
                    value=value if value is not None else 0,
                    timestamp=now,
                    quality=quality,
                )

            # Handle addresses that failed to parse
            for addr in addresses:
                if addr not in result:
                    result[addr] = TagValue(
                        value=0,
                        timestamp=now,
                        quality=Quality.BAD_CONFIG_ERROR,
                    )

            return result

        except Exception as e:
            self._health.record_error(str(e))
            logger.warning(
                "Read failed",
                connector=self.name,
                addresses=addresses,
                error=str(e),
            )

            # Return bad quality values
            now = datetime.now(timezone.utc)
            return {
                addr: TagValue(
                    value=0,
                    timestamp=now,
                    quality=Quality.BAD_NO_COMMUNICATION,
                )
                for addr in addresses
            }

    async def _do_read(self, addresses: list[str]) -> dict[str, Any]:
        """Read multiple nodes from OPC UA server.

        Uses batch read via read_values() for efficiency.

        Args:
            addresses: List of NodeId address strings to read

        Returns:
            Dictionary mapping addresses to values

        Raises:
            ConnectionError: If not connected
        """
        if not self._client:
            raise ConnectionError("Not connected")

        results: dict[str, Any] = {}

        # Parse NodeIds and get nodes
        nodes = []
        valid_addresses = []

        for addr in addresses:
            try:
                node_id = parse_node_id(addr)
                node = self._client.get_node(node_id)
                nodes.append(node)
                valid_addresses.append(addr)
            except ValueError as e:
                logger.warning(
                    "Failed to parse NodeId",
                    address=addr,
                    error=str(e),
                )

        if not nodes:
            return results

        # Batch read all nodes
        data_values = await self._client.read_values(nodes)

        # Process results
        for addr, dv in zip(valid_addresses, data_values):
            quality = _status_code_to_quality(dv.StatusCode)

            if quality.is_good() or quality == Quality.UNCERTAIN:
                # Extract value from DataValue
                value = dv.Value.Value if dv.Value is not None else None
                results[addr] = value
            else:
                # For bad quality, still include in results with None value
                # The base class will handle quality mapping
                results[addr] = None

        return results

    async def _do_write(self, address: str, value: Any) -> None:
        """Write a single value to OPC UA server.

        Args:
            address: NodeId address string
            value: Value to write

        Raises:
            ConnectionError: If not connected
            ValueError: If NodeId is invalid
        """
        if not self._client:
            raise ConnectionError("Not connected")

        node_id = parse_node_id(address)
        node = self._client.get_node(node_id)

        await node.write_value(value)

        logger.debug(
            "OPC UA write successful",
            address=address,
            value=value,
        )
