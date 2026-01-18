"""Pydantic schemas for WebUI API.

Provides request/response models for the REST API endpoints.
All models use Pydantic v2 for validation and serialization.
"""

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
from mtp_gateway.adapters.northbound.webui.schemas.tags import (
    TagListResponse,
    TagValue,
    TagWriteRequest,
)
from mtp_gateway.adapters.northbound.webui.schemas.services import (
    ServiceCommand,
    ServiceCommandRequest,
    ServiceListResponse,
    ServiceResponse,
    ServiceState,
)
from mtp_gateway.adapters.northbound.webui.schemas.alarms import (
    AlarmAckRequest,
    AlarmListResponse,
    AlarmResponse,
    AlarmState,
)
from mtp_gateway.adapters.northbound.webui.schemas.history import (
    HistoryQueryParams,
    HistoryResponse,
    HistoryDataPoint,
)

__all__ = [
    # Auth
    "LoginRequest",
    "LoginResponse",
    "RefreshRequest",
    "TokenResponse",
    "UserResponse",
    # Common
    "ErrorResponse",
    "PaginatedResponse",
    "SuccessResponse",
    # Tags
    "TagListResponse",
    "TagValue",
    "TagWriteRequest",
    # Services
    "ServiceCommand",
    "ServiceCommandRequest",
    "ServiceListResponse",
    "ServiceResponse",
    "ServiceState",
    # Alarms
    "AlarmAckRequest",
    "AlarmListResponse",
    "AlarmResponse",
    "AlarmState",
    # History
    "HistoryQueryParams",
    "HistoryResponse",
    "HistoryDataPoint",
]
