"""Protocol-specific address validators for MTP Gateway.

Validates tag addresses based on the target protocol, providing
clear error messages for invalid address formats.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar


@dataclass
class ValidationResult:
    """Result of address validation."""

    valid: bool
    error: str | None = None
    normalized: str | None = None  # Normalized form of address if valid


class AddressValidator(ABC):
    """Base class for protocol-specific address validators."""

    @property
    @abstractmethod
    def protocol_name(self) -> str:
        """Human-readable protocol name for error messages."""
        ...

    @abstractmethod
    def validate(self, address: str) -> ValidationResult:
        """Validate an address string.

        Args:
            address: Raw address string from configuration.

        Returns:
            ValidationResult with validity status and any errors.
        """
        ...

    def __call__(self, address: str) -> ValidationResult:
        """Allow validator to be called directly."""
        return self.validate(address)


class ModbusAddressValidator(AddressValidator):
    """Validator for Modbus register addresses.

    Supports standard Modbus addressing:
    - Coils: 00001-09999 (discrete outputs)
    - Discrete Inputs: 10001-19999
    - Input Registers: 30001-39999
    - Holding Registers: 40001-49999

    Also supports extended addressing (6-digit) and zero-based forms.
    """

    # Pattern: 1-6 digits with optional colon-separated unit ID
    _ADDRESS_PATTERN = re.compile(r"^(\d+:)?(\d{1,6})$")

    # Valid function code ranges (1-indexed)
    _VALID_RANGES: ClassVar[list[tuple[int, int, str]]] = [
        (1, 9999, "coils"),
        (10001, 19999, "discrete_inputs"),
        (30001, 39999, "input_registers"),
        (40001, 49999, "holding_registers"),
        # Extended ranges
        (100001, 165535, "extended_coils"),
        (300001, 365535, "extended_input_registers"),
        (400001, 465535, "extended_holding_registers"),
    ]

    @property
    def protocol_name(self) -> str:
        return "Modbus"

    def validate(self, address: str) -> ValidationResult:
        """Validate Modbus address format.

        Args:
            address: Modbus address like '40001' or '1:40001' (with unit ID).

        Returns:
            ValidationResult with normalized address.
        """
        address = address.strip()

        match = self._ADDRESS_PATTERN.match(address)
        if not match:
            return ValidationResult(
                valid=False,
                error=f"Invalid Modbus address format: '{address}'. "
                "Expected numeric address like '40001' or '1:40001'.",
            )

        unit_prefix = match.group(1) or ""
        addr_str = match.group(2)

        try:
            addr_num = int(addr_str)
        except ValueError:
            return ValidationResult(
                valid=False, error=f"Address '{addr_str}' is not a valid number."
            )

        # Check if in any valid range
        for range_start, range_end, _range_name in self._VALID_RANGES:
            if range_start <= addr_num <= range_end:
                return ValidationResult(
                    valid=True,
                    normalized=f"{unit_prefix}{addr_num}",
                )

        # Provide helpful error for invalid ranges
        return ValidationResult(
            valid=False,
            error=f"Modbus address {addr_num} is not in a standard register range. "
            "Valid ranges: 00001-09999 (coils), 10001-19999 (inputs), "
            "30001-39999 (input regs), 40001-49999 (holding regs).",
        )


class S7AddressValidator(AddressValidator):
    """Validator for Siemens S7 PLC addresses.

    Supports:
    - Data blocks: DB1.DBX0.0, DB1.DBW0, DB1.DBD0, DB100.DBX10.5
    - Inputs: I0.0, IB0, IW0, ID0
    - Outputs: Q0.0, QB0, QW0, QD0
    - Markers: M0.0, MB0, MW0, MD0
    - Timers: T0
    - Counters: C0
    """

    # Pattern for DB addresses: DB<num>.DB<type><offset>[.bit]
    _DB_PATTERN = re.compile(
        r"^DB(\d+)\.DB([XBWD])(\d+)(?:\.(\d))?$", re.IGNORECASE
    )

    # Pattern for I/O/M addresses: <area>[<type>]<offset>[.bit]
    _AREA_PATTERN = re.compile(
        r"^([IQMT])([BWD])?(\d+)(?:\.(\d))?$", re.IGNORECASE
    )

    # Counter pattern
    _COUNTER_PATTERN = re.compile(r"^C(\d+)$", re.IGNORECASE)

    @property
    def protocol_name(self) -> str:
        return "S7"

    def validate(self, address: str) -> ValidationResult:  # noqa: PLR0911, PLR0912
        """Validate S7 address format.

        Args:
            address: S7 address like 'DB1.DBW0' or 'M0.0'.

        Returns:
            ValidationResult with normalized address.
        """
        address = address.strip()

        # Try DB address pattern
        db_match = self._DB_PATTERN.match(address)
        if db_match:
            db_num = int(db_match.group(1))
            data_type = db_match.group(2).upper()
            offset = int(db_match.group(3))
            bit = db_match.group(4)

            # Validate bit number for DBX type
            if data_type == "X":
                if bit is None:
                    return ValidationResult(
                        valid=False,
                        error=f"Bit address DBX requires bit number (0-7): '{address}'.",
                    )
                if int(bit) > 7:
                    return ValidationResult(
                        valid=False,
                        error=f"Bit number must be 0-7, got {bit}.",
                    )
                normalized = f"DB{db_num}.DBX{offset}.{bit}"
            else:
                if bit is not None:
                    return ValidationResult(
                        valid=False,
                        error=f"Type {data_type} should not have bit index: '{address}'.",
                    )
                normalized = f"DB{db_num}.DB{data_type}{offset}"

            return ValidationResult(valid=True, normalized=normalized)

        # Try area address pattern (I, Q, M, T)
        area_match = self._AREA_PATTERN.match(address)
        if area_match:
            area = area_match.group(1).upper()
            data_type = (area_match.group(2) or "X").upper()
            offset = int(area_match.group(3))
            bit = area_match.group(4)

            # Handle Timer special case
            if area == "T":
                if data_type not in ("X", ""):
                    return ValidationResult(
                        valid=False,
                        error=f"Timer T{offset} should not have type modifier.",
                    )
                return ValidationResult(valid=True, normalized=f"T{offset}")

            # Validate bit for bit-level access
            if data_type == "X" or (data_type == "" and bit is not None):
                if bit is None:
                    return ValidationResult(
                        valid=False,
                        error=f"Bit address requires bit number: '{address}'.",
                    )
                if int(bit) > 7:
                    return ValidationResult(
                        valid=False,
                        error=f"Bit number must be 0-7, got {bit}.",
                    )
                normalized = f"{area}{offset}.{bit}"
            else:
                if bit is not None:
                    return ValidationResult(
                        valid=False,
                        error=f"Type {data_type} should not have bit index.",
                    )
                normalized = f"{area}{data_type}{offset}"

            return ValidationResult(valid=True, normalized=normalized)

        # Try counter pattern
        counter_match = self._COUNTER_PATTERN.match(address)
        if counter_match:
            return ValidationResult(
                valid=True,
                normalized=f"C{counter_match.group(1)}",
            )

        return ValidationResult(
            valid=False,
            error=f"Invalid S7 address format: '{address}'. "
            "Expected formats: DB1.DBW0, M0.0, I0.0, Q0.0, T0, C0.",
        )


class EIPAddressValidator(AddressValidator):
    """Validator for EtherNet/IP (CIP) tag paths.

    Supports:
    - Simple tags: MyTag, Tag_Name
    - Array elements: MyArray[0], MyArray[1,2]
    - Struct members: MyStruct.Member
    - Program-scoped tags: Program:MainProgram.Tag
    """

    # Valid tag name: starts with letter/underscore, alphanumeric after
    _TAG_NAME = r"[A-Za-z_][A-Za-z0-9_]*"

    # Array index pattern: [n] or [n,n,...]
    _ARRAY_INDEX = r"\[\d+(?:,\d+)*\]"

    # Full tag path pattern
    _TAG_PATTERN = re.compile(
        rf"^(?:Program:{_TAG_NAME}\.)?{_TAG_NAME}(?:{_ARRAY_INDEX})?(?:\.{_TAG_NAME}(?:{_ARRAY_INDEX})?)*$"
    )

    @property
    def protocol_name(self) -> str:
        return "EtherNet/IP"

    def validate(self, address: str) -> ValidationResult:
        """Validate EtherNet/IP tag path.

        Args:
            address: CIP tag path like 'MyTag' or 'MyStruct.Member[0]'.

        Returns:
            ValidationResult with normalized address.
        """
        address = address.strip()

        if not address:
            return ValidationResult(
                valid=False, error="Tag path cannot be empty."
            )

        if not self._TAG_PATTERN.match(address):
            return ValidationResult(
                valid=False,
                error=f"Invalid EtherNet/IP tag path: '{address}'. "
                "Tag names must start with letter/underscore, followed by "
                "alphanumerics/underscores. Use dots for structure members, "
                "brackets for arrays.",
            )

        return ValidationResult(valid=True, normalized=address)


class OPCUANodeIdValidator(AddressValidator):
    """Validator for OPC UA NodeId strings.

    Supports:
    - Numeric: ns=2;i=1234
    - String: ns=2;s=MyNode
    - GUID: ns=2;g=12345678-1234-1234-1234-123456789abc
    - Opaque: ns=2;b=base64data
    - Expanded: nsu=urn:example;s=MyNode
    """

    # Standard NodeId patterns
    _NUMERIC_PATTERN = re.compile(r"^ns=(\d+);i=(\d+)$")
    _STRING_PATTERN = re.compile(r"^ns=(\d+);s=(.+)$")
    _GUID_PATTERN = re.compile(
        r"^ns=(\d+);g=([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"
    )
    _OPAQUE_PATTERN = re.compile(r"^ns=(\d+);b=([A-Za-z0-9+/=]+)$")

    # Expanded NodeId patterns (with namespace URI)
    _EXPANDED_STRING_PATTERN = re.compile(r"^nsu=([^;]+);s=(.+)$")
    _EXPANDED_NUMERIC_PATTERN = re.compile(r"^nsu=([^;]+);i=(\d+)$")

    @property
    def protocol_name(self) -> str:
        return "OPC UA"

    def validate(self, address: str) -> ValidationResult:
        """Validate OPC UA NodeId string.

        Args:
            address: NodeId like 'ns=2;s=MyNode' or 'nsu=urn:example;s=Tag1'.

        Returns:
            ValidationResult with normalized address.
        """
        address = address.strip()

        if not address:
            return ValidationResult(
                valid=False, error="NodeId cannot be empty."
            )

        # Check each pattern
        patterns = [
            (self._NUMERIC_PATTERN, "numeric"),
            (self._STRING_PATTERN, "string"),
            (self._GUID_PATTERN, "guid"),
            (self._OPAQUE_PATTERN, "opaque"),
            (self._EXPANDED_STRING_PATTERN, "expanded_string"),
            (self._EXPANDED_NUMERIC_PATTERN, "expanded_numeric"),
        ]

        for pattern, _type_name in patterns:
            if pattern.match(address):
                return ValidationResult(valid=True, normalized=address)

        return ValidationResult(
            valid=False,
            error=f"Invalid OPC UA NodeId format: '{address}'. "
            "Expected formats: ns=2;i=1234 (numeric), ns=2;s=MyTag (string), "
            "nsu=urn:example;s=MyTag (expanded).",
        )


def get_validator_for_protocol(protocol: str) -> AddressValidator | None:
    """Get the appropriate validator for a protocol name.

    Args:
        protocol: Protocol name (modbus, s7, eip, opcua, etc.)

    Returns:
        AddressValidator instance or None if unknown protocol.
    """
    validators: dict[str, type[AddressValidator]] = {
        "modbus": ModbusAddressValidator,
        "modbus_tcp": ModbusAddressValidator,
        "modbus_rtu": ModbusAddressValidator,
        "s7": S7AddressValidator,
        "siemens": S7AddressValidator,
        "eip": EIPAddressValidator,
        "ethernet_ip": EIPAddressValidator,
        "cip": EIPAddressValidator,
        "opcua": OPCUANodeIdValidator,
        "opc_ua": OPCUANodeIdValidator,
        "opcua_client": OPCUANodeIdValidator,
    }

    protocol_lower = protocol.lower().replace("-", "_").replace(" ", "_")
    validator_class = validators.get(protocol_lower)

    if validator_class:
        return validator_class()
    return None


def validate_tag_address(
    address: str,
    connector_type: str,
) -> ValidationResult:
    """Validate a tag address for a specific connector type.

    Args:
        address: Tag address string.
        connector_type: Type of connector (modbus, s7, eip, opcua, etc.)

    Returns:
        ValidationResult with validity status.
    """
    validator = get_validator_for_protocol(connector_type)

    if validator is None:
        # Unknown protocol - allow any address
        return ValidationResult(valid=True, normalized=address)

    return validator.validate(address)
