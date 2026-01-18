"""History endpoints router.

Provides endpoints for tag history queries using TimescaleDB time-series features.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from mtp_gateway.adapters.northbound.webui.dependencies import (
    CurrentUserDep,
    require_permission,
)
from mtp_gateway.adapters.northbound.webui.schemas.history import (
    AggregateFunction,
    HistoryDataPoint,
    HistoryResponse,
    MultiTagHistoryResponse,
    TagHistoryData,
)
from mtp_gateway.adapters.northbound.webui.security.rbac import Permission

if TYPE_CHECKING:
    from mtp_gateway.adapters.northbound.webui.database.repository import (
        HistoryRepository,
    )

logger = structlog.get_logger(__name__)

router = APIRouter()


def _get_history_repository(request: Request) -> "HistoryRepository | None":
    """Get history repository from app state if database is configured."""
    db_pool = getattr(request.app.state, "db_pool", None)
    if db_pool and db_pool.is_connected:
        from mtp_gateway.adapters.northbound.webui.database.repository import (
            HistoryRepository,
        )

        return HistoryRepository(db_pool.pool)
    return None


HistoryRepoDep = Annotated["HistoryRepository | None", Depends(_get_history_repository)]


def _parse_datetime(dt_str: str) -> datetime:
    """Parse ISO 8601 datetime string.

    Args:
        dt_str: ISO 8601 formatted datetime string

    Returns:
        Parsed datetime (UTC if no timezone)

    Raises:
        HTTPException: If parsing fails
    """
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        # Ensure UTC if no timezone
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid datetime format: {dt_str}. Use ISO 8601 format (e.g., 2024-01-15T10:30:00Z)",
        ) from e


def _validate_bucket_size(bucket_size: str) -> str:
    """Validate time bucket size.

    Args:
        bucket_size: Bucket size string (e.g., "1m", "1h")

    Returns:
        Validated bucket size

    Raises:
        HTTPException: If invalid bucket size
    """
    valid_buckets = {"1s", "5s", "10s", "30s", "1m", "5m", "15m", "30m", "1h", "4h", "1d"}
    if bucket_size not in valid_buckets:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid bucket_size: {bucket_size}. Valid values: {sorted(valid_buckets)}",
        )
    return bucket_size


@router.get(
    "/tags",
    response_model=HistoryResponse,
    dependencies=[Depends(require_permission(Permission.HISTORY_READ))],
)
async def get_tag_history(
    current_user: CurrentUserDep,
    history_repo: HistoryRepoDep,
    tag: str = Query(..., description="Tag name to query"),
    start: str = Query(..., description="Start time (ISO 8601)"),
    end: str = Query(..., description="End time (ISO 8601)"),
    aggregate: AggregateFunction = Query(
        default=AggregateFunction.NONE,
        description="Aggregation function",
    ),
    bucket: str = Query(
        default="1m",
        description="Time bucket size (1s, 5s, 10s, 30s, 1m, 5m, 15m, 30m, 1h, 4h, 1d)",
    ),
    limit: int = Query(default=1000, ge=1, le=10000, description="Max data points"),
) -> HistoryResponse:
    """Query tag history with optional aggregation.

    Requires: history:read permission

    Use aggregation for large time ranges to reduce data volume:
    - 1s-10s buckets for last hour
    - 1m-5m buckets for last day
    - 1h buckets for last week
    - 1d buckets for last month

    Args:
        current_user: Authenticated user
        history_repo: History repository
        tag: Tag name to query
        start: Start time (ISO 8601)
        end: End time (ISO 8601)
        aggregate: Aggregation function (none, avg, min, max, sum, count, first, last)
        bucket: Time bucket for aggregation
        limit: Maximum data points to return

    Returns:
        Historical data points for the tag

    Raises:
        HTTPException: If database not configured or invalid parameters
    """
    # Parse and validate parameters
    start_time = _parse_datetime(start)
    end_time = _parse_datetime(end)
    bucket_size = _validate_bucket_size(bucket)

    if start_time >= end_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Start time must be before end time",
        )

    if history_repo is None:
        # Return empty response if no database
        logger.warning(
            "History query without database",
            tag=tag,
            username=current_user.username,
        )
        return HistoryResponse(
            tag_name=tag,
            start_time=start,
            end_time=end,
            aggregate=aggregate,
            bucket_size=bucket_size,
            data=[],
            count=0,
        )

    # Query database
    records = await history_repo.query(
        tag_name=tag,
        start_time=start_time,
        end_time=end_time,
        aggregate=aggregate.value,
        bucket_size=bucket_size,
        limit=limit,
    )

    # Convert to response format
    data = [
        HistoryDataPoint(
            timestamp=record.time.isoformat(),
            value=record.value,
            quality=record.quality,
        )
        for record in records
    ]

    logger.debug(
        "Tag history queried",
        username=current_user.username,
        tag=tag,
        count=len(data),
        aggregate=aggregate.value,
    )

    return HistoryResponse(
        tag_name=tag,
        start_time=start,
        end_time=end,
        aggregate=aggregate,
        bucket_size=bucket_size,
        data=data,
        count=len(data),
    )


@router.get(
    "/tags/multi",
    response_model=MultiTagHistoryResponse,
    dependencies=[Depends(require_permission(Permission.HISTORY_READ))],
)
async def get_multi_tag_history(
    current_user: CurrentUserDep,
    history_repo: HistoryRepoDep,
    tags: str = Query(..., description="Comma-separated tag names (max 10)"),
    start: str = Query(..., description="Start time (ISO 8601)"),
    end: str = Query(..., description="End time (ISO 8601)"),
    aggregate: AggregateFunction = Query(
        default=AggregateFunction.AVG,
        description="Aggregation function",
    ),
    bucket: str = Query(
        default="1m",
        description="Time bucket size",
    ),
    limit: int = Query(default=1000, ge=1, le=10000, description="Max data points per tag"),
) -> MultiTagHistoryResponse:
    """Query history for multiple tags simultaneously.

    Requires: history:read permission

    Efficient for trend charts showing multiple tags. All tags use the
    same time range and aggregation settings.

    Args:
        current_user: Authenticated user
        history_repo: History repository
        tags: Comma-separated tag names (max 10)
        start: Start time (ISO 8601)
        end: End time (ISO 8601)
        aggregate: Aggregation function
        bucket: Time bucket for aggregation
        limit: Maximum data points per tag

    Returns:
        Historical data for all requested tags

    Raises:
        HTTPException: If database not configured or invalid parameters
    """
    # Parse tag names
    tag_names = [t.strip() for t in tags.split(",") if t.strip()]
    if not tag_names:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No tag names provided",
        )
    if len(tag_names) > 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 10 tags per query",
        )

    # Parse and validate parameters
    start_time = _parse_datetime(start)
    end_time = _parse_datetime(end)
    bucket_size = _validate_bucket_size(bucket)

    if start_time >= end_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Start time must be before end time",
        )

    if history_repo is None:
        # Return empty response if no database
        logger.warning(
            "Multi-tag history query without database",
            tags=tag_names,
            username=current_user.username,
        )
        return MultiTagHistoryResponse(
            start_time=start,
            end_time=end,
            aggregate=aggregate,
            bucket_size=bucket_size,
            tags=[TagHistoryData(tag_name=t, data=[], count=0) for t in tag_names],
        )

    # Query database
    results = await history_repo.query_multi(
        tag_names=tag_names,
        start_time=start_time,
        end_time=end_time,
        aggregate=aggregate.value,
        bucket_size=bucket_size,
        limit=limit,
    )

    # Convert to response format
    tag_data = []
    for tag_name in tag_names:
        records = results.get(tag_name, [])
        data = [
            HistoryDataPoint(
                timestamp=record.time.isoformat(),
                value=record.value,
                quality=record.quality,
            )
            for record in records
        ]
        tag_data.append(
            TagHistoryData(
                tag_name=tag_name,
                data=data,
                count=len(data),
            )
        )

    logger.debug(
        "Multi-tag history queried",
        username=current_user.username,
        tags=tag_names,
        total_points=sum(t.count for t in tag_data),
    )

    return MultiTagHistoryResponse(
        start_time=start,
        end_time=end,
        aggregate=aggregate,
        bucket_size=bucket_size,
        tags=tag_data,
    )


@router.get(
    "/tags/available",
    response_model=list[str],
    dependencies=[Depends(require_permission(Permission.HISTORY_READ))],
)
async def get_available_tags(
    current_user: CurrentUserDep,
    history_repo: HistoryRepoDep,
) -> list[str]:
    """Get list of tags with available history data.

    Requires: history:read permission

    Returns:
        List of tag names that have history data
    """
    if history_repo is None:
        return []

    tags = await history_repo.get_available_tags()

    logger.debug(
        "Available history tags queried",
        username=current_user.username,
        count=len(tags),
    )

    return tags
