"""Tag schemas for WebUI API.

Provides request/response models for tag read/write operations.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TagQuality(str, Enum):
    """Tag value quality indicators.

    Based on OPC UA quality codes.
    """

    GOOD = "good"
    BAD = "bad"
    UNCERTAIN = "uncertain"
    NOT_CONNECTED = "not_connected"


class TagValue(BaseModel):
    """Tag value with metadata.

    Attributes:
        name: Tag name/identifier
        value: Current tag value
        quality: Data quality indicator
        timestamp: ISO 8601 timestamp of last update
        unit: Engineering unit (optional)
        datatype: Data type (e.g., "float32", "bool")
        writable: Whether tag can be written
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Tag name")
    value: Any = Field(..., description="Current value")
    quality: TagQuality = Field(default=TagQuality.GOOD, description="Data quality")
    timestamp: str = Field(..., description="ISO 8601 timestamp")
    unit: str = Field(default="", description="Engineering unit")
    datatype: str = Field(default="", description="Data type")
    writable: bool = Field(default=False, description="Write enabled")


class TagListResponse(BaseModel):
    """Response for tag list endpoint.

    Attributes:
        tags: List of tag values
        count: Total number of tags
    """

    model_config = ConfigDict(extra="forbid")

    tags: list[TagValue] = Field(default_factory=list, description="Tag values")
    count: int = Field(..., ge=0, description="Total tag count")


class TagWriteRequest(BaseModel):
    """Request to write a tag value.

    Attributes:
        value: Value to write to the tag
    """

    model_config = ConfigDict(extra="forbid")

    value: Any = Field(..., description="Value to write")


class TagWriteResponse(BaseModel):
    """Response for tag write operation.

    Attributes:
        success: Whether write succeeded
        name: Tag that was written
        previous_value: Value before write
        new_value: Value after write
        timestamp: ISO 8601 timestamp of write
    """

    model_config = ConfigDict(extra="forbid")

    success: bool = Field(default=True, description="Write success")
    name: str = Field(..., description="Tag name")
    previous_value: Any = Field(default=None, description="Previous value")
    new_value: Any = Field(..., description="Written value")
    timestamp: str = Field(..., description="ISO 8601 timestamp")


class TagSubscriptionRequest(BaseModel):
    """Request to subscribe to tag updates.

    Used for WebSocket subscriptions.

    Attributes:
        tags: List of tag names to subscribe to (empty for all)
        interval_ms: Minimum update interval in milliseconds
    """

    model_config = ConfigDict(extra="forbid")

    tags: list[str] = Field(default_factory=list, description="Tags to subscribe")
    interval_ms: int = Field(
        default=1000,
        ge=100,
        le=60000,
        description="Update interval",
    )
