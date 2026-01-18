"""Alarm endpoints router.

Provides endpoints for alarm management per ISA-18.2.
Supports both database-backed and in-memory storage modes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status

from mtp_gateway.adapters.northbound.webui.dependencies import (
    CurrentUserDep,
    require_permission,
)
from mtp_gateway.adapters.northbound.webui.schemas.alarms import (
    AlarmAckRequest,
    AlarmAckResponse,
    AlarmListResponse,
    AlarmResponse,
    AlarmShelveRequest,
    AlarmState,
)
from mtp_gateway.adapters.northbound.webui.security.rbac import Permission

if TYPE_CHECKING:
    from mtp_gateway.adapters.northbound.webui.database.repository import (
        AlarmRecord,
        AlarmRepository,
    )

logger = structlog.get_logger(__name__)

router = APIRouter()


# In-memory alarm storage - used when database is not configured
_MOCK_ALARMS: dict[int, dict] = {
    1: {
        "id": 1,
        "alarm_id": "TEMP_HIGH_001",
        "source": "ReactorTemp",
        "priority": 2,
        "state": "active",
        "message": "Reactor temperature high",
        "value": 105.5,
        "raised_at": "2024-01-15T10:30:00Z",
        "acknowledged_at": None,
        "acknowledged_by": None,
        "cleared_at": None,
        "shelved_until": None,
    },
    2: {
        "id": 2,
        "alarm_id": "LEVEL_LOW_002",
        "source": "TankLevel",
        "priority": 3,
        "state": "acknowledged",
        "message": "Tank level below setpoint",
        "value": 15.2,
        "raised_at": "2024-01-15T09:15:00Z",
        "acknowledged_at": "2024-01-15T09:20:00Z",
        "acknowledged_by": "operator",
        "cleared_at": None,
        "shelved_until": None,
    },
}
_NEXT_ALARM_ID = 3


def _format_alarm_response(alarm_data: dict) -> AlarmResponse:
    """Format alarm data dict for API response."""
    return AlarmResponse(
        id=alarm_data["id"],
        alarm_id=alarm_data["alarm_id"],
        source=alarm_data["source"],
        priority=alarm_data["priority"],
        state=AlarmState(alarm_data["state"]),
        message=alarm_data["message"],
        value=alarm_data["value"],
        raised_at=alarm_data["raised_at"],
        acknowledged_at=alarm_data["acknowledged_at"],
        acknowledged_by=alarm_data["acknowledged_by"],
        cleared_at=alarm_data["cleared_at"],
        shelved_until=alarm_data["shelved_until"],
    )


def _format_alarm_record(record: "AlarmRecord") -> AlarmResponse:
    """Format AlarmRecord from database for API response."""
    return AlarmResponse(
        id=record.id,
        alarm_id=record.alarm_id,
        source=record.source,
        priority=record.priority,
        state=AlarmState(record.state),
        message=record.message,
        value=record.value,
        raised_at=record.raised_at.isoformat() if record.raised_at else None,
        acknowledged_at=record.acknowledged_at.isoformat() if record.acknowledged_at else None,
        acknowledged_by=record.acknowledged_by_username,
        cleared_at=record.cleared_at.isoformat() if record.cleared_at else None,
        shelved_until=record.shelved_until.isoformat() if record.shelved_until else None,
    )


def _get_alarm_repository(request: Request) -> "AlarmRepository | None":
    """Get alarm repository from app state if database is configured."""
    db_pool = getattr(request.app.state, "db_pool", None)
    if db_pool and db_pool.is_connected:
        from mtp_gateway.adapters.northbound.webui.database.repository import (
            AlarmRepository,
        )

        return AlarmRepository(db_pool.pool)
    return None


AlarmRepoDep = Annotated["AlarmRepository | None", Depends(_get_alarm_repository)]


@router.get(
    "",
    response_model=AlarmListResponse,
    dependencies=[Depends(require_permission(Permission.ALARMS_READ))],
)
async def list_alarms(
    current_user: CurrentUserDep,
    alarm_repo: AlarmRepoDep,
    state: AlarmState | None = None,
    priority: int | None = None,
    source: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> AlarmListResponse:
    """List alarms with optional filtering.

    Requires: alarms:read permission

    Args:
        current_user: Authenticated user
        alarm_repo: Alarm repository (database or None for mock)
        state: Filter by alarm state
        priority: Filter by priority level
        source: Filter by source (partial match)
        limit: Maximum results
        offset: Results offset

    Returns:
        List of alarms matching filters
    """
    if alarm_repo:
        # Database mode
        alarms, total, active_count, unacknowledged_count = await alarm_repo.get_all(
            state=state.value if state else None,
            priority=priority,
            source=source,
            limit=limit,
            offset=offset,
        )
        alarm_responses = [_format_alarm_record(a) for a in alarms]
    else:
        # In-memory mock mode
        alarm_responses: list[AlarmResponse] = []
        active_count = 0
        unacknowledged_count = 0

        for alarm_data in _MOCK_ALARMS.values():
            # Apply filters
            if state and alarm_data["state"] != state.value:
                continue
            if priority and alarm_data["priority"] != priority:
                continue
            if source and source.lower() not in alarm_data["source"].lower():
                continue

            alarm_responses.append(_format_alarm_response(alarm_data))

            # Count active and unacknowledged
            if alarm_data["state"] == "active":
                active_count += 1
                unacknowledged_count += 1
            elif alarm_data["state"] == "acknowledged":
                active_count += 1

        # Apply pagination
        total = len(alarm_responses)
        alarm_responses = alarm_responses[offset : offset + limit]

    logger.debug(
        "Listed alarms",
        username=current_user.username,
        count=len(alarm_responses),
        total=total if alarm_repo else len(alarm_responses),
        mode="database" if alarm_repo else "mock",
    )

    return AlarmListResponse(
        alarms=alarm_responses,
        count=total if alarm_repo else len(alarm_responses) + offset,
        active_count=active_count,
        unacknowledged_count=unacknowledged_count,
    )


@router.get(
    "/{alarm_id}",
    response_model=AlarmResponse,
    dependencies=[Depends(require_permission(Permission.ALARMS_READ))],
)
async def get_alarm(
    alarm_id: int,
    current_user: CurrentUserDep,
    alarm_repo: AlarmRepoDep,
) -> AlarmResponse:
    """Get a single alarm by ID.

    Requires: alarms:read permission

    Args:
        alarm_id: Alarm database ID
        current_user: Authenticated user
        alarm_repo: Alarm repository

    Returns:
        Alarm details

    Raises:
        HTTPException: If alarm not found
    """
    if alarm_repo:
        record = await alarm_repo.get_by_id(alarm_id)
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Alarm not found: {alarm_id}",
            )
        return _format_alarm_record(record)
    else:
        alarm_data = _MOCK_ALARMS.get(alarm_id)
        if not alarm_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Alarm not found: {alarm_id}",
            )
        return _format_alarm_response(alarm_data)


@router.post(
    "/{alarm_id}/acknowledge",
    response_model=AlarmAckResponse,
    dependencies=[Depends(require_permission(Permission.ALARMS_ACK))],
)
async def acknowledge_alarm(
    alarm_id: int,
    request: AlarmAckRequest,
    current_user: CurrentUserDep,
    alarm_repo: AlarmRepoDep,
) -> AlarmAckResponse:
    """Acknowledge an alarm.

    Requires: alarms:ack permission

    Args:
        alarm_id: Alarm database ID
        request: Acknowledgment request with optional comment
        current_user: Authenticated user
        alarm_repo: Alarm repository

    Returns:
        Acknowledgment result

    Raises:
        HTTPException: If alarm not found or already acknowledged
    """
    now = datetime.now(UTC).isoformat()

    if alarm_repo:
        # Get user_id from the database (simplified - use 1 for now)
        # In production, you'd lookup user_id from current_user.username
        record = await alarm_repo.acknowledge(
            alarm_id=alarm_id,
            user_id=1,  # TODO: Look up user_id from username
            username=current_user.username,
        )
        if not record:
            # Check if alarm exists
            existing = await alarm_repo.get_by_id(alarm_id)
            if not existing:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Alarm not found: {alarm_id}",
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Alarm is not in active state: {existing.state}",
            )
        ack_time = record.acknowledged_at.isoformat() if record.acknowledged_at else now
    else:
        alarm_data = _MOCK_ALARMS.get(alarm_id)
        if not alarm_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Alarm not found: {alarm_id}",
            )

        if alarm_data["state"] != "active":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Alarm is not in active state: {alarm_data['state']}",
            )

        # Update alarm state
        alarm_data["state"] = "acknowledged"
        alarm_data["acknowledged_at"] = now
        alarm_data["acknowledged_by"] = current_user.username
        ack_time = now

    logger.info(
        "Alarm acknowledged",
        username=current_user.username,
        alarm_id=alarm_id,
        comment=request.comment,
    )

    return AlarmAckResponse(
        success=True,
        alarm_id=alarm_id,
        acknowledged_at=ack_time,
        acknowledged_by=current_user.username,
    )


@router.post(
    "/{alarm_id}/clear",
    response_model=AlarmResponse,
    dependencies=[Depends(require_permission(Permission.ALARMS_ACK))],
)
async def clear_alarm(
    alarm_id: int,
    current_user: CurrentUserDep,
    alarm_repo: AlarmRepoDep,
) -> AlarmResponse:
    """Clear an acknowledged alarm.

    Requires: alarms:ack permission

    Args:
        alarm_id: Alarm database ID
        current_user: Authenticated user
        alarm_repo: Alarm repository

    Returns:
        Updated alarm

    Raises:
        HTTPException: If alarm not found or not acknowledged
    """
    if alarm_repo:
        record = await alarm_repo.clear(alarm_id, current_user.username)
        if not record:
            existing = await alarm_repo.get_by_id(alarm_id)
            if not existing:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Alarm not found: {alarm_id}",
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Alarm must be acknowledged before clearing: {existing.state}",
            )
        return _format_alarm_record(record)
    else:
        alarm_data = _MOCK_ALARMS.get(alarm_id)
        if not alarm_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Alarm not found: {alarm_id}",
            )

        if alarm_data["state"] != "acknowledged":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Alarm must be acknowledged before clearing: {alarm_data['state']}",
            )

        # Update alarm state
        now = datetime.now(UTC).isoformat()
        alarm_data["state"] = "cleared"
        alarm_data["cleared_at"] = now

        logger.info(
            "Alarm cleared",
            username=current_user.username,
            alarm_id=alarm_id,
        )

        return _format_alarm_response(alarm_data)


@router.post(
    "/{alarm_id}/shelve",
    response_model=AlarmResponse,
    dependencies=[Depends(require_permission(Permission.ALARMS_SHELVE))],
)
async def shelve_alarm(
    alarm_id: int,
    request: AlarmShelveRequest,
    current_user: CurrentUserDep,
    alarm_repo: AlarmRepoDep,
) -> AlarmResponse:
    """Shelve an alarm temporarily.

    Requires: alarms:shelve permission

    Args:
        alarm_id: Alarm database ID
        request: Shelve request with duration and reason
        current_user: Authenticated user
        alarm_repo: Alarm repository

    Returns:
        Updated alarm

    Raises:
        HTTPException: If alarm not found or cannot be shelved
    """
    if alarm_repo:
        record = await alarm_repo.shelve(
            alarm_id=alarm_id,
            duration_minutes=request.duration_minutes,
            reason=request.reason,
            username=current_user.username,
        )
        if not record:
            existing = await alarm_repo.get_by_id(alarm_id)
            if not existing:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Alarm not found: {alarm_id}",
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Alarm cannot be shelved in state: {existing.state}",
            )
        return _format_alarm_record(record)
    else:
        alarm_data = _MOCK_ALARMS.get(alarm_id)
        if not alarm_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Alarm not found: {alarm_id}",
            )

        if alarm_data["state"] not in ("active", "acknowledged"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Alarm cannot be shelved in state: {alarm_data['state']}",
            )

        # Calculate shelve expiry
        from datetime import timedelta

        shelved_until = datetime.now(UTC) + timedelta(minutes=request.duration_minutes)
        alarm_data["state"] = "shelved"
        alarm_data["shelved_until"] = shelved_until.isoformat()

        logger.info(
            "Alarm shelved",
            username=current_user.username,
            alarm_id=alarm_id,
            duration_minutes=request.duration_minutes,
            reason=request.reason,
        )

        return _format_alarm_response(alarm_data)


# Functions for programmatic alarm management (used by AlarmDetector)


async def raise_alarm(
    alarm_repo: "AlarmRepository | None",
    alarm_id: str,
    source: str,
    priority: int,
    message: str,
    value: float | None = None,
) -> int | None:
    """Raise a new alarm programmatically.

    Used by AlarmDetector service when monitor values exceed limits.

    Args:
        alarm_repo: Alarm repository or None for mock mode
        alarm_id: Logical alarm identifier
        source: Source data assembly
        priority: Priority level (1-4)
        message: Alarm message
        value: Triggering value

    Returns:
        Created alarm database ID or None
    """
    global _NEXT_ALARM_ID

    if alarm_repo:
        # Check if alarm already active for this source
        existing = await alarm_repo.find_active_alarm(alarm_id, source)
        if existing:
            logger.debug(
                "Alarm already active",
                alarm_id=alarm_id,
                source=source,
            )
            return existing.id

        record = await alarm_repo.create(
            alarm_id=alarm_id,
            source=source,
            priority=priority,
            message=message,
            value=value,
        )
        return record.id
    else:
        # Check mock alarms
        for alarm_data in _MOCK_ALARMS.values():
            if (
                alarm_data["alarm_id"] == alarm_id
                and alarm_data["source"] == source
                and alarm_data["state"] in ("active", "acknowledged")
            ):
                return alarm_data["id"]

        # Create new mock alarm
        new_id = _NEXT_ALARM_ID
        _NEXT_ALARM_ID += 1
        _MOCK_ALARMS[new_id] = {
            "id": new_id,
            "alarm_id": alarm_id,
            "source": source,
            "priority": priority,
            "state": "active",
            "message": message,
            "value": value,
            "raised_at": datetime.now(UTC).isoformat(),
            "acknowledged_at": None,
            "acknowledged_by": None,
            "cleared_at": None,
            "shelved_until": None,
        }
        logger.info(
            "Alarm raised (mock)",
            alarm_id=alarm_id,
            source=source,
            priority=priority,
        )
        return new_id


async def auto_clear_alarm(
    alarm_repo: "AlarmRepository | None",
    alarm_id: str,
    source: str,
) -> bool:
    """Auto-clear an alarm when condition is no longer present.

    Used by AlarmDetector when monitor values return to normal.

    Args:
        alarm_repo: Alarm repository or None for mock mode
        alarm_id: Logical alarm identifier
        source: Source data assembly

    Returns:
        True if alarm was cleared, False if not found
    """
    if alarm_repo:
        record = await alarm_repo.auto_clear_if_condition_gone(alarm_id, source)
        return record is not None
    else:
        for db_id, alarm_data in list(_MOCK_ALARMS.items()):
            if (
                alarm_data["alarm_id"] == alarm_id
                and alarm_data["source"] == source
                and alarm_data["state"] in ("active", "acknowledged")
            ):
                alarm_data["state"] = "cleared"
                alarm_data["cleared_at"] = datetime.now(UTC).isoformat()
                logger.info(
                    "Alarm auto-cleared (mock)",
                    alarm_id=alarm_id,
                    source=source,
                )
                return True
        return False
