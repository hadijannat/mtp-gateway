"""Common schemas shared across API endpoints.

Provides base models for pagination, errors, and success responses.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

# Generic type for paginated items
T = TypeVar("T")


class SuccessResponse(BaseModel):
    """Generic success response."""

    model_config = ConfigDict(extra="forbid")

    success: bool = True
    message: str = "Operation completed successfully"


class ErrorResponse(BaseModel):
    """Standard error response format.

    Attributes:
        error: Error type/code
        message: Human-readable error message
        detail: Additional error details (optional)
    """

    model_config = ConfigDict(extra="forbid")

    error: str = Field(..., description="Error type or code")
    message: str = Field(..., description="Human-readable error message")
    detail: Any = Field(default=None, description="Additional error details")


class PaginationMeta(BaseModel):
    """Pagination metadata for list responses.

    Attributes:
        total: Total number of items
        page: Current page number (1-based)
        page_size: Number of items per page
        total_pages: Total number of pages
    """

    model_config = ConfigDict(extra="forbid")

    total: int = Field(..., ge=0, description="Total number of items")
    page: int = Field(..., ge=1, description="Current page number")
    page_size: int = Field(..., ge=1, le=1000, description="Items per page")
    total_pages: int = Field(..., ge=0, description="Total number of pages")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response wrapper.

    Attributes:
        items: List of items for current page
        pagination: Pagination metadata
    """

    model_config = ConfigDict(extra="forbid")

    items: list[T] = Field(default_factory=list, description="Page items")
    pagination: PaginationMeta


class TimestampMixin(BaseModel):
    """Mixin for models with timestamps.

    Uses ISO 8601 format for consistency.
    """

    created_at: str | None = Field(default=None, description="ISO 8601 creation timestamp")
    updated_at: str | None = Field(default=None, description="ISO 8601 update timestamp")
