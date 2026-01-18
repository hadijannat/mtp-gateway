"""Health check endpoints.

Provides endpoints for monitoring server health and readiness.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter()


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(..., description="Health status")
    timestamp: str = Field(..., description="ISO 8601 timestamp")
    version: str = Field(default="1.0.0", description="API version")


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Check server health.

    Returns basic health status. Use for load balancer health checks.
    """
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now(UTC).isoformat(),
    )


@router.get("/ready", response_model=HealthResponse)
async def readiness_check() -> HealthResponse:
    """Check server readiness.

    Returns readiness status. Server is ready when all components
    are initialized and accepting requests.
    """
    return HealthResponse(
        status="ready",
        timestamp=datetime.now(UTC).isoformat(),
    )
