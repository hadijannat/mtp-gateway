"""Persistence layer for MTP Gateway.

Provides SQLite-based persistent storage for:
- Service state snapshots (crash recovery)
- Tag value history (time-series queries)
- Command audit logging (compliance/debugging)
"""

from mtp_gateway.adapters.persistence.models import (
    CommandAuditLog,
    ServiceStateSnapshot,
    TagValueRecord,
)
from mtp_gateway.adapters.persistence.repository import PersistenceRepository

__all__ = [
    "PersistenceRepository",
    "ServiceStateSnapshot",
    "TagValueRecord",
    "CommandAuditLog",
]
