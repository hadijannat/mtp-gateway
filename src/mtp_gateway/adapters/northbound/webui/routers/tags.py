"""Tag endpoints router.

Provides endpoints for reading and writing tag values.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from mtp_gateway.adapters.northbound.webui.dependencies import (
    CurrentUserDep,
    TagManagerDep,
    require_permission,
)
from mtp_gateway.adapters.northbound.webui.schemas.tags import (
    TagListResponse,
    TagQuality,
    TagValue,
    TagWriteRequest,
    TagWriteResponse,
)
from mtp_gateway.adapters.northbound.webui.security.rbac import Permission

if TYPE_CHECKING:
    from mtp_gateway.application.tag_manager import TagManager

logger = structlog.get_logger(__name__)

router = APIRouter()


def _quality_to_enum(quality: Any) -> TagQuality:
    """Convert tag quality to enum."""
    quality_str = str(quality.value).lower() if hasattr(quality, "value") else str(quality).lower()

    if "good" in quality_str:
        return TagQuality.GOOD
    elif "bad" in quality_str:
        return TagQuality.BAD
    elif "uncertain" in quality_str:
        return TagQuality.UNCERTAIN
    else:
        return TagQuality.NOT_CONNECTED


def _format_tag_value(name: str, tag_manager: TagManager) -> TagValue:
    """Format a tag value for API response."""
    tag_state = tag_manager.get_tag(name)
    if tag_state is None:
        return TagValue(
            name=name,
            value=None,
            quality=TagQuality.NOT_CONNECTED,
            timestamp=datetime.now(UTC).isoformat(),
            unit="",
            datatype="",
            writable=False,
        )

    tag_value = tag_state.current_value
    timestamp = tag_value.timestamp if tag_value and tag_value.timestamp else datetime.now(UTC)
    timestamp_str = timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp)

    return TagValue(
        name=name,
        value=tag_value.value if tag_value else None,
        quality=_quality_to_enum(tag_state.quality),
        timestamp=timestamp_str,
        unit=tag_state.definition.unit,
        datatype=tag_state.definition.datatype.value,
        writable=tag_state.definition.writable,
    )


@router.get(
    "",
    response_model=TagListResponse,
    dependencies=[Depends(require_permission(Permission.TAGS_READ))],
)
async def list_tags(
    current_user: CurrentUserDep,
    tag_manager: TagManagerDep,
) -> TagListResponse:
    """List all tags with current values.

    Requires: tags:read permission

    Args:
        current_user: Authenticated user
        tag_manager: Tag manager instance

    Returns:
        List of all tags with values
    """
    tags: list[TagValue] = []

    # Get all tag names from manager
    tag_names = tag_manager.get_all_tag_names()

    for name in tag_names:
        tags.append(_format_tag_value(name, tag_manager))

    logger.debug(
        "Listed tags",
        username=current_user.username,
        count=len(tags),
    )

    return TagListResponse(
        tags=tags,
        count=len(tags),
    )


@router.get(
    "/{tag_name:path}",
    response_model=TagValue,
    dependencies=[Depends(require_permission(Permission.TAGS_READ))],
)
async def get_tag(
    tag_name: str,
    _current_user: CurrentUserDep,
    tag_manager: TagManagerDep,
) -> TagValue:
    """Get a single tag value.

    Requires: tags:read permission

    Args:
        tag_name: Tag name to read
        current_user: Authenticated user
        tag_manager: Tag manager instance

    Returns:
        Tag value

    Raises:
        HTTPException: If tag not found
    """
    tag_value = tag_manager.get_tag(tag_name)

    if tag_value is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tag not found: {tag_name}",
        )

    return _format_tag_value(tag_name, tag_manager)


@router.post(
    "/{tag_name:path}",
    response_model=TagWriteResponse,
    dependencies=[Depends(require_permission(Permission.TAGS_WRITE))],
)
async def write_tag(
    tag_name: str,
    request: TagWriteRequest,
    current_user: CurrentUserDep,
    tag_manager: TagManagerDep,
) -> TagWriteResponse:
    """Write a value to a tag.

    Requires: tags:write permission

    Args:
        tag_name: Tag name to write
        request: Value to write
        current_user: Authenticated user
        tag_manager: Tag manager instance

    Returns:
        Write result

    Raises:
        HTTPException: If tag not found or write fails
    """
    # Get current value for response
    current = tag_manager.get_value(tag_name)
    previous_value = current.value if current else None

    try:
        # Attempt write
        await tag_manager.write_tag(tag_name, request.value)

        logger.info(
            "Tag written",
            username=current_user.username,
            tag=tag_name,
            value=request.value,
        )

        return TagWriteResponse(
            success=True,
            name=tag_name,
            previous_value=previous_value,
            new_value=request.value,
            timestamp=datetime.now(UTC).isoformat(),
        )

    except ValueError as e:
        logger.warning(
            "Tag write failed",
            username=current_user.username,
            tag=tag_name,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    except Exception as e:
        logger.exception(
            "Tag write error",
            username=current_user.username,
            tag=tag_name,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Write failed: {e}",
        ) from e
