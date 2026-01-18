"""Tag domain models for MTP Gateway.

Tags represent data points from PLCs mapped to the gateway. Each tag has:
- A value with associated timestamp and quality
- Metadata for scaling, units, and data type
- Reference to the source connector and address
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class Quality(Enum):
    """OPC UA-compatible data quality codes.

    Based on OPC UA StatusCode categories for representing
    the reliability of tag values.
    """

    # Good quality - value is reliable
    GOOD = "Good"
    GOOD_LOCAL_OVERRIDE = "Good_LocalOverride"

    # Uncertain quality - value may not be current
    UNCERTAIN = "Uncertain"
    UNCERTAIN_NO_COMM_LAST_USABLE = "Uncertain_NoCommunicationLastUsable"
    UNCERTAIN_SENSOR_NOT_ACCURATE = "Uncertain_SensorNotAccurate"
    UNCERTAIN_LAST_USABLE_VALUE = "Uncertain_LastUsableValue"

    # Bad quality - value is not usable
    BAD = "Bad"
    BAD_NO_COMMUNICATION = "Bad_NoCommunication"
    BAD_SENSOR_FAILURE = "Bad_SensorFailure"
    BAD_NOT_CONNECTED = "Bad_NotConnected"
    BAD_DEVICE_FAILURE = "Bad_DeviceFailure"
    BAD_CONFIG_ERROR = "Bad_ConfigurationError"
    BAD_OUT_OF_SERVICE = "Bad_OutOfService"

    def is_good(self) -> bool:
        """Check if quality indicates good/reliable data."""
        return self.value.startswith("Good")

    def is_uncertain(self) -> bool:
        """Check if quality indicates uncertain data."""
        return self.value.startswith("Uncertain")

    def is_bad(self) -> bool:
        """Check if quality indicates bad/unusable data."""
        return self.value.startswith("Bad")

    def to_opcua_status_code(self) -> int:
        """Convert to OPC UA StatusCode numeric value."""
        # Mapping based on OPC UA Part 8 StatusCodes
        mapping = {
            Quality.GOOD: 0x00000000,
            Quality.GOOD_LOCAL_OVERRIDE: 0x00D80000,
            Quality.UNCERTAIN: 0x40000000,
            Quality.UNCERTAIN_NO_COMM_LAST_USABLE: 0x408F0000,
            Quality.UNCERTAIN_SENSOR_NOT_ACCURATE: 0x40930000,
            Quality.UNCERTAIN_LAST_USABLE_VALUE: 0x408C0000,
            Quality.BAD: 0x80000000,
            Quality.BAD_NO_COMMUNICATION: 0x80310000,
            Quality.BAD_SENSOR_FAILURE: 0x80320000,
            Quality.BAD_NOT_CONNECTED: 0x80AB0000,
            Quality.BAD_DEVICE_FAILURE: 0x80330000,
            Quality.BAD_CONFIG_ERROR: 0x80890000,
            Quality.BAD_OUT_OF_SERVICE: 0x808A0000,
        }
        return mapping.get(self, 0x80000000)


class DataType(Enum):
    """Supported PLC data types."""

    BOOL = "bool"
    INT16 = "int16"
    UINT16 = "uint16"
    INT32 = "int32"
    UINT32 = "uint32"
    INT64 = "int64"
    UINT64 = "uint64"
    FLOAT32 = "float32"
    FLOAT64 = "float64"
    STRING = "string"

    def python_type(self) -> type:
        """Get corresponding Python type."""
        mapping: dict[DataType, type] = {
            DataType.BOOL: bool,
            DataType.INT16: int,
            DataType.UINT16: int,
            DataType.INT32: int,
            DataType.UINT32: int,
            DataType.INT64: int,
            DataType.UINT64: int,
            DataType.FLOAT32: float,
            DataType.FLOAT64: float,
            DataType.STRING: str,
        }
        return mapping[self]

    def byte_size(self) -> int:
        """Get size in bytes (0 for variable-length types)."""
        sizes = {
            DataType.BOOL: 1,
            DataType.INT16: 2,
            DataType.UINT16: 2,
            DataType.INT32: 4,
            DataType.UINT32: 4,
            DataType.INT64: 8,
            DataType.UINT64: 8,
            DataType.FLOAT32: 4,
            DataType.FLOAT64: 8,
            DataType.STRING: 0,
        }
        return sizes[self]


@dataclass(frozen=True, slots=True)
class TagValue:
    """Immutable snapshot of a tag's value at a point in time.

    Attributes:
        value: The actual value (type depends on tag's DataType)
        timestamp: When the value was sampled from the PLC
        quality: Data quality indicator
        source_timestamp: Original timestamp from PLC (if available)
    """

    value: float | int | bool | str
    timestamp: datetime
    quality: Quality
    source_timestamp: datetime | None = None

    @classmethod
    def good(cls, value: float | int | bool | str) -> TagValue:
        """Create a good quality TagValue with current timestamp."""
        now = datetime.now(UTC)
        return cls(value=value, timestamp=now, quality=Quality.GOOD)

    @classmethod
    def bad_no_comm(cls, last_value: float | int | bool | str | None = None) -> TagValue:
        """Create a bad quality TagValue for communication failure."""
        now = datetime.now(UTC)
        return cls(
            value=last_value if last_value is not None else 0,
            timestamp=now,
            quality=Quality.BAD_NO_COMMUNICATION,
        )

    @classmethod
    def uncertain_last_usable(cls, last_value: TagValue) -> TagValue:
        """Create uncertain quality from a previously good value."""
        now = datetime.now(UTC)
        return cls(
            value=last_value.value,
            timestamp=now,
            quality=Quality.UNCERTAIN_NO_COMM_LAST_USABLE,
            source_timestamp=last_value.timestamp,
        )


@dataclass(frozen=True, slots=True)
class ScaleConfig:
    """Linear scaling configuration for analog values.

    Applies: scaled = raw * gain + offset
    """

    gain: float = 1.0
    offset: float = 0.0

    def apply(self, raw_value: float | int) -> float:
        """Apply scaling to raw value."""
        return float(raw_value) * self.gain + self.offset

    def reverse(self, scaled_value: float) -> float:
        """Reverse scaling to get raw value."""
        if self.gain == 0:
            raise ValueError("Cannot reverse scale with zero gain")
        return (scaled_value - self.offset) / self.gain


@dataclass(slots=True)
class TagDefinition:
    """Configuration for a tag mapping from PLC to gateway.

    Attributes:
        name: Unique identifier for this tag in the gateway
        connector: Name of the connector providing this tag
        address: Protocol-specific address (e.g., "40001" for Modbus)
        datatype: Expected data type
        writable: Whether writes are permitted
        scale: Optional linear scaling
        unit: Engineering unit string (e.g., "degC", "bar")
        description: Human-readable description
    """

    name: str
    connector: str
    address: str
    datatype: DataType
    writable: bool = False
    scale: ScaleConfig | None = None
    unit: str = ""
    description: str = ""
    byte_order: str = "big"
    word_order: str = "big"

    def apply_scale(self, raw_value: float | int) -> float:
        """Apply scaling if configured."""
        if self.scale:
            return self.scale.apply(raw_value)
        return float(raw_value)

    def reverse_scale(self, scaled_value: float) -> float:
        """Reverse scaling if configured."""
        if self.scale:
            return self.scale.reverse(scaled_value)
        return scaled_value


@dataclass(slots=True)
class TagState:
    """Mutable state for a tag during runtime.

    Tracks current value, history, and statistics.
    """

    definition: TagDefinition
    current_value: TagValue | None = None
    last_good_value: TagValue | None = None
    read_count: int = 0
    write_count: int = 0
    error_count: int = 0
    _value_changed_callbacks: list[Any] = field(default_factory=list)

    def update(self, new_value: TagValue) -> None:
        """Update the tag with a new value."""
        old_value = self.current_value
        self.current_value = new_value
        self.read_count += 1

        if new_value.quality.is_good():
            self.last_good_value = new_value
        elif new_value.quality.is_bad():
            self.error_count += 1

        # Notify subscribers if value changed
        if old_value is None or old_value.value != new_value.value:
            for callback in self._value_changed_callbacks:
                callback(self.definition.name, new_value)

    def subscribe(self, callback: Any) -> None:
        """Subscribe to value change notifications."""
        self._value_changed_callbacks.append(callback)

    def unsubscribe(self, callback: Any) -> None:
        """Unsubscribe from value change notifications."""
        if callback in self._value_changed_callbacks:
            self._value_changed_callbacks.remove(callback)

    @property
    def quality(self) -> Quality:
        """Get current quality or BAD if no value."""
        if self.current_value:
            return self.current_value.quality
        return Quality.BAD_NOT_CONNECTED
