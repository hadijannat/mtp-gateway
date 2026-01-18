"""Alarm schemas for WebUI API.

Provides request/response models for alarm management per ISA-18.2.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class AlarmState(str, Enum):
    """Alarm states per ISA-18.2.

    State transitions:
    - ACTIVE: Alarm condition is true, not acknowledged
    - ACKNOWLEDGED: Alarm condition is true, acknowledged by operator
    - CLEARED: Alarm condition is false, was acknowledged
    - SHELVED: Alarm temporarily suppressed
    """

    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    CLEARED = "cleared"
    SHELVED = "shelved"


class AlarmPriority(int, Enum):
    """Alarm priority levels per ISA-18.2.

    1 = Emergency/Critical
    2 = High
    3 = Medium
    4 = Low/Advisory
    """

    CRITICAL = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4


class AlarmResponse(BaseModel):
    """Single alarm response.

    Attributes:
        id: Alarm database ID
        alarm_id: Logical alarm identifier
        source: Source data assembly or tag
        priority: Priority level (1-4)
        state: Current alarm state
        message: Alarm message text
        value: Value that triggered the alarm
        raised_at: ISO 8601 timestamp when raised
        acknowledged_at: ISO 8601 timestamp when acknowledged
        acknowledged_by: Username who acknowledged
        cleared_at: ISO 8601 timestamp when cleared
        shelved_until: ISO 8601 timestamp when shelve expires
    """

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., description="Alarm ID")
    alarm_id: str = Field(..., description="Logical alarm identifier")
    source: str = Field(..., description="Alarm source")
    priority: int = Field(..., ge=1, le=4, description="Priority (1-4)")
    state: AlarmState = Field(..., description="Current state")
    message: str = Field(..., description="Alarm message")
    value: float | None = Field(default=None, description="Trigger value")
    raised_at: str = Field(..., description="ISO 8601 raised timestamp")
    acknowledged_at: str | None = Field(default=None, description="ISO 8601 ack timestamp")
    acknowledged_by: str | None = Field(default=None, description="Acknowledging user")
    cleared_at: str | None = Field(default=None, description="ISO 8601 cleared timestamp")
    shelved_until: str | None = Field(default=None, description="ISO 8601 shelve expiry")


class AlarmListResponse(BaseModel):
    """Response for alarm list endpoint.

    Attributes:
        alarms: List of alarms
        count: Total number of alarms matching filter
        active_count: Number of active alarms
        unacknowledged_count: Number of unacknowledged alarms
    """

    model_config = ConfigDict(extra="forbid")

    alarms: list[AlarmResponse] = Field(default_factory=list, description="Alarms")
    count: int = Field(..., ge=0, description="Total alarm count")
    active_count: int = Field(default=0, ge=0, description="Active alarm count")
    unacknowledged_count: int = Field(default=0, ge=0, description="Unacknowledged count")


class AlarmAckRequest(BaseModel):
    """Request to acknowledge an alarm.

    Attributes:
        comment: Optional acknowledgment comment
    """

    model_config = ConfigDict(extra="forbid")

    comment: str | None = Field(
        default=None,
        max_length=500,
        description="Acknowledgment comment",
    )


class AlarmAckResponse(BaseModel):
    """Response for alarm acknowledgment.

    Attributes:
        success: Whether acknowledgment succeeded
        alarm_id: Acknowledged alarm ID
        acknowledged_at: ISO 8601 timestamp
        acknowledged_by: Username who acknowledged
    """

    model_config = ConfigDict(extra="forbid")

    success: bool = Field(default=True, description="Ack success")
    alarm_id: int = Field(..., description="Alarm ID")
    acknowledged_at: str = Field(..., description="ISO 8601 ack timestamp")
    acknowledged_by: str = Field(..., description="Acknowledging user")


class AlarmShelveRequest(BaseModel):
    """Request to shelve an alarm.

    Attributes:
        duration_minutes: Shelve duration in minutes
        reason: Reason for shelving
    """

    model_config = ConfigDict(extra="forbid")

    duration_minutes: int = Field(
        ...,
        ge=1,
        le=1440,  # Max 24 hours
        description="Shelve duration in minutes",
    )
    reason: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Shelve reason",
    )


class AlarmQueryParams(BaseModel):
    """Query parameters for alarm list endpoint.

    Attributes:
        state: Filter by alarm state
        priority: Filter by priority level
        source: Filter by source (partial match)
        since: Only alarms raised after this ISO 8601 timestamp
        limit: Maximum results to return
        offset: Results offset for pagination
    """

    model_config = ConfigDict(extra="forbid")

    state: AlarmState | None = Field(default=None, description="Filter by state")
    priority: int | None = Field(default=None, ge=1, le=4, description="Filter by priority")
    source: str | None = Field(default=None, description="Filter by source")
    since: str | None = Field(default=None, description="Raised after timestamp")
    limit: int = Field(default=100, ge=1, le=1000, description="Max results")
    offset: int = Field(default=0, ge=0, description="Results offset")
