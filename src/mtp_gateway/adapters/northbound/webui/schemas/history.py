"""History schemas for WebUI API.

Provides request/response models for tag history queries.
Designed for efficient time-series data retrieval from TimescaleDB.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class AggregateFunction(str, Enum):
    """Aggregation functions for history queries.

    Used to downsample high-resolution data for charting.
    """

    NONE = "none"  # Raw data
    AVG = "avg"  # Average
    MIN = "min"  # Minimum
    MAX = "max"  # Maximum
    SUM = "sum"  # Sum
    COUNT = "count"  # Count
    FIRST = "first"  # First value in bucket
    LAST = "last"  # Last value in bucket


class HistoryDataPoint(BaseModel):
    """Single history data point.

    Attributes:
        timestamp: ISO 8601 timestamp
        value: Tag value at this time
        quality: Data quality indicator
    """

    model_config = ConfigDict(extra="forbid")

    timestamp: str = Field(..., description="ISO 8601 timestamp")
    value: float | None = Field(..., description="Tag value")
    quality: str = Field(default="good", description="Data quality")


class HistoryQueryParams(BaseModel):
    """Query parameters for tag history.

    Attributes:
        tag_name: Tag to query (required)
        start_time: Start of time range (ISO 8601)
        end_time: End of time range (ISO 8601)
        aggregate: Aggregation function
        bucket_size: Time bucket size for aggregation (e.g., "1m", "1h", "1d")
        limit: Maximum data points to return
    """

    model_config = ConfigDict(extra="forbid")

    tag_name: str = Field(..., min_length=1, description="Tag name")
    start_time: str = Field(..., description="ISO 8601 start time")
    end_time: str = Field(..., description="ISO 8601 end time")
    aggregate: AggregateFunction = Field(
        default=AggregateFunction.NONE,
        description="Aggregation function",
    )
    bucket_size: str = Field(
        default="1m",
        description="Time bucket (1s, 1m, 5m, 1h, 1d)",
    )
    limit: int = Field(
        default=1000,
        ge=1,
        le=10000,
        description="Max data points",
    )


class HistoryResponse(BaseModel):
    """Response for tag history query.

    Attributes:
        tag_name: Queried tag name
        start_time: Query start time
        end_time: Query end time
        aggregate: Aggregation used
        bucket_size: Time bucket size
        data: Historical data points
        count: Number of data points returned
    """

    model_config = ConfigDict(extra="forbid")

    tag_name: str = Field(..., description="Tag name")
    start_time: str = Field(..., description="Query start time")
    end_time: str = Field(..., description="Query end time")
    aggregate: AggregateFunction = Field(..., description="Aggregation used")
    bucket_size: str = Field(..., description="Time bucket size")
    data: list[HistoryDataPoint] = Field(default_factory=list, description="Data points")
    count: int = Field(..., ge=0, description="Data point count")


class MultiTagHistoryQueryParams(BaseModel):
    """Query parameters for multiple tag history.

    Attributes:
        tag_names: List of tags to query
        start_time: Start of time range (ISO 8601)
        end_time: End of time range (ISO 8601)
        aggregate: Aggregation function
        bucket_size: Time bucket size for aggregation
        limit: Maximum data points per tag
    """

    model_config = ConfigDict(extra="forbid")

    tag_names: list[str] = Field(
        ...,
        min_length=1,
        max_length=10,
        description="Tag names (max 10)",
    )
    start_time: str = Field(..., description="ISO 8601 start time")
    end_time: str = Field(..., description="ISO 8601 end time")
    aggregate: AggregateFunction = Field(
        default=AggregateFunction.AVG,
        description="Aggregation function",
    )
    bucket_size: str = Field(
        default="1m",
        description="Time bucket (1s, 1m, 5m, 1h, 1d)",
    )
    limit: int = Field(
        default=1000,
        ge=1,
        le=10000,
        description="Max data points per tag",
    )


class TagHistoryData(BaseModel):
    """History data for a single tag.

    Attributes:
        tag_name: Tag name
        data: Historical data points
        count: Number of data points
    """

    model_config = ConfigDict(extra="forbid")

    tag_name: str = Field(..., description="Tag name")
    data: list[HistoryDataPoint] = Field(default_factory=list, description="Data points")
    count: int = Field(..., ge=0, description="Data point count")


class MultiTagHistoryResponse(BaseModel):
    """Response for multiple tag history query.

    Attributes:
        start_time: Query start time
        end_time: Query end time
        aggregate: Aggregation used
        bucket_size: Time bucket size
        tags: History data per tag
    """

    model_config = ConfigDict(extra="forbid")

    start_time: str = Field(..., description="Query start time")
    end_time: str = Field(..., description="Query end time")
    aggregate: AggregateFunction = Field(..., description="Aggregation used")
    bucket_size: str = Field(..., description="Time bucket size")
    tags: list[TagHistoryData] = Field(default_factory=list, description="Per-tag history")
