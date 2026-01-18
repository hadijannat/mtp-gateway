"""Database layer for WebUI.

Provides async PostgreSQL connection pool and repository pattern
for alarms and tag history using TimescaleDB.
"""

from mtp_gateway.adapters.northbound.webui.database.connection import (
    DatabasePool,
    get_db_pool,
)
from mtp_gateway.adapters.northbound.webui.database.repository import (
    AlarmRepository,
    HistoryRepository,
)

__all__ = [
    "DatabasePool",
    "get_db_pool",
    "AlarmRepository",
    "HistoryRepository",
]
