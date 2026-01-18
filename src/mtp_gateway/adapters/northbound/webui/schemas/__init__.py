"""Pydantic schemas for WebUI API.

Provides request/response models for the REST API endpoints.
All models use Pydantic v2 for validation and serialization.
"""

from mtp_gateway.adapters.northbound.webui.schemas.alarms import (
    AlarmAckRequest,
    AlarmListResponse,
    AlarmResponse,
    AlarmState,
)
from mtp_gateway.adapters.northbound.webui.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    TokenResponse,
    UserResponse,
)
from mtp_gateway.adapters.northbound.webui.schemas.common import (
    ErrorResponse,
    PaginatedResponse,
    SuccessResponse,
)
from mtp_gateway.adapters.northbound.webui.schemas.history import (
    HistoryDataPoint,
    HistoryQueryParams,
    HistoryResponse,
)
from mtp_gateway.adapters.northbound.webui.schemas.services import (
    ServiceCommand,
    ServiceCommandRequest,
    ServiceListResponse,
    ServiceResponse,
    ServiceState,
)
from mtp_gateway.adapters.northbound.webui.schemas.tags import (
    TagListResponse,
    TagValue,
    TagWriteRequest,
)

__all__ = [
    "AlarmAckRequest",
    "AlarmListResponse",
    "AlarmResponse",
    "AlarmState",
    "ErrorResponse",
    "HistoryDataPoint",
    "HistoryQueryParams",
    "HistoryResponse",
    "LoginRequest",
    "LoginResponse",
    "PaginatedResponse",
    "RefreshRequest",
    "ServiceCommand",
    "ServiceCommandRequest",
    "ServiceListResponse",
    "ServiceResponse",
    "ServiceState",
    "SuccessResponse",
    "TagListResponse",
    "TagValue",
    "TagWriteRequest",
    "TokenResponse",
    "UserResponse",
]
