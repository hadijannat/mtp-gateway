"""Repository for persistent storage operations.

Provides async database access for service state recovery, tag history,
and command audit logging. Uses SQLAlchemy 2.0 async mode with aiosqlite.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from mtp_gateway.adapters.persistence.models import (
    Base,
    CommandAuditLog,
    ServiceStateSnapshot,
    TagValueRecord,
)
from mtp_gateway.domain.model.tags import Quality

logger = structlog.get_logger(__name__)


class PersistenceRepository:
    """Repository for persistent storage operations.

    Provides async access to SQLite database for:
    - Service state snapshots (crash recovery)
    - Tag value history (time-series queries)
    - Command audit logging (compliance/debugging)

    Uses SQLAlchemy 2.0 async mode with aiosqlite driver.

    Example:
        >>> repo = PersistenceRepository(db_path="gateway.db")
        >>> await repo.initialize()
        >>> await repo.save_service_state("Reactor1", PackMLState.EXECUTE, ...)
    """

    def __init__(self, db_path: str = "mtp_gateway.db") -> None:
        """Initialize the repository.

        Args:
            db_path: Path to SQLite database file.
                     Use ":memory:" for in-memory database (tests).
        """
        self._db_path = db_path
        # Build connection URL
        if db_path == ":memory:":
            # In-memory requires shared cache for multi-connection access
            url = "sqlite+aiosqlite:///:memory:?cache=shared"
        else:
            url = f"sqlite+aiosqlite:///{db_path}"

        self._engine = create_async_engine(
            url,
            echo=False,
            # Use NullPool for SQLite to avoid connection issues
            pool_pre_ping=True,
        )
        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        logger.debug("Persistence repository initialized", db_path=db_path)

    async def initialize(self) -> None:
        """Create database tables if they don't exist.

        Safe to call multiple times (idempotent).
        """
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables initialized", db_path=self._db_path)

    async def close(self) -> None:
        """Close database connections."""
        await self._engine.dispose()
        logger.debug("Persistence repository closed")

    # -------------------------------------------------------------------------
    # Service State Operations
    # -------------------------------------------------------------------------

    async def save_service_state(
        self,
        service_name: str,
        state: Any,  # PackMLState enum
        procedure_id: int | None,
        parameters: dict[str, Any],
    ) -> None:
        """Save or update service state snapshot.

        Upserts the service state - creates if new, updates if exists.
        Uses SQLite INSERT OR REPLACE to handle concurrent updates safely.

        Args:
            service_name: Unique service identifier
            state: PackML state (enum or value)
            procedure_id: Active procedure ID
            parameters: Procedure parameters
        """
        # Convert state enum to string if needed
        state_str = state.name if hasattr(state, "name") else str(state)
        params_json = json.dumps(parameters) if parameters else "{}"
        now = datetime.now(timezone.utc)

        async with self._session_factory() as session:
            # Use SQLite upsert (INSERT OR REPLACE via on_conflict_do_update)
            stmt = sqlite_insert(ServiceStateSnapshot).values(
                service_name=service_name,
                state=state_str,
                procedure_id=procedure_id,
                parameters=params_json,
                started_at=now,
                updated_at=now,
            )
            # On conflict with service_name, update the other fields
            stmt = stmt.on_conflict_do_update(
                index_elements=["service_name"],
                set_={
                    "state": state_str,
                    "procedure_id": procedure_id,
                    "parameters": params_json,
                    "updated_at": now,
                },
            )
            await session.execute(stmt)
            await session.commit()
            logger.debug(
                "Service state saved",
                service=service_name,
                state=state_str,
            )

    async def get_service_state(
        self, service_name: str
    ) -> ServiceStateSnapshot | None:
        """Get service state snapshot by name.

        Args:
            service_name: Service identifier

        Returns:
            ServiceStateSnapshot or None if not found
        """
        async with self._session_factory() as session:
            stmt = select(ServiceStateSnapshot).where(
                ServiceStateSnapshot.service_name == service_name
            )
            result = await session.execute(stmt)
            snapshot = result.scalar_one_or_none()

            if snapshot:
                # Deserialize parameters JSON
                if isinstance(snapshot.parameters, str):
                    snapshot.parameters = json.loads(snapshot.parameters)

            return snapshot

    async def delete_service_state(self, service_name: str) -> None:
        """Delete service state snapshot.

        Safe to call for non-existent service (no-op).

        Args:
            service_name: Service identifier
        """
        async with self._session_factory() as session:
            stmt = delete(ServiceStateSnapshot).where(
                ServiceStateSnapshot.service_name == service_name
            )
            await session.execute(stmt)
            await session.commit()
            logger.debug("Service state deleted", service=service_name)

    async def get_all_service_states(self) -> list[ServiceStateSnapshot]:
        """Get all service state snapshots.

        Returns:
            List of all persisted service states
        """
        async with self._session_factory() as session:
            stmt = select(ServiceStateSnapshot)
            result = await session.execute(stmt)
            snapshots = list(result.scalars().all())

            # Deserialize parameters JSON
            for snapshot in snapshots:
                if isinstance(snapshot.parameters, str):
                    snapshot.parameters = json.loads(snapshot.parameters)

            return snapshots

    # -------------------------------------------------------------------------
    # Tag History Operations
    # -------------------------------------------------------------------------

    async def record_tag_value(
        self,
        tag_name: str,
        value: float | int | bool | str,
        quality: Quality,
        timestamp: datetime,
        source_timestamp: datetime | None = None,
    ) -> None:
        """Record a tag value for historical storage.

        Appends a new record to the tag history.

        Args:
            tag_name: Tag identifier
            value: Tag value
            quality: OPC UA quality
            timestamp: Gateway timestamp
            source_timestamp: Source timestamp from PLC
        """
        # Convert quality enum to string
        quality_str = quality.name if hasattr(quality, "name") else str(quality)
        # Serialize value to JSON
        value_json = json.dumps(value)

        async with self._session_factory() as session:
            record = TagValueRecord(
                tag_name=tag_name,
                value=value_json,
                quality=quality_str,
                timestamp=timestamp,
                source_timestamp=source_timestamp,
            )
            session.add(record)
            await session.commit()

    async def get_tag_history(
        self,
        tag_name: str,
        start: datetime,
        end: datetime,
    ) -> list[TagValueRecord]:
        """Get tag value history within time range.

        Args:
            tag_name: Tag identifier
            start: Start of time range (inclusive)
            end: End of time range (inclusive)

        Returns:
            List of TagValueRecord ordered by timestamp ascending
        """
        async with self._session_factory() as session:
            stmt = (
                select(TagValueRecord)
                .where(
                    TagValueRecord.tag_name == tag_name,
                    TagValueRecord.timestamp >= start,
                    TagValueRecord.timestamp <= end,
                )
                .order_by(TagValueRecord.timestamp.asc())
            )
            result = await session.execute(stmt)
            records = list(result.scalars().all())

            # Deserialize value JSON and restore timezone info
            for record in records:
                if isinstance(record.value, str):
                    record.value = json.loads(record.value)
                # SQLite doesn't preserve timezone info, restore UTC
                if record.timestamp and record.timestamp.tzinfo is None:
                    record.timestamp = record.timestamp.replace(tzinfo=timezone.utc)
                if record.source_timestamp and record.source_timestamp.tzinfo is None:
                    record.source_timestamp = record.source_timestamp.replace(
                        tzinfo=timezone.utc
                    )

            return records

    # -------------------------------------------------------------------------
    # Command Audit Log Operations
    # -------------------------------------------------------------------------

    async def log_command(
        self,
        timestamp: datetime,
        command_type: str,
        target: str,
        parameters: dict[str, Any] | None = None,
        result: str = "SUCCESS",
        error_message: str | None = None,
    ) -> None:
        """Log a command execution for audit purposes.

        Args:
            timestamp: When the command was issued
            command_type: Type of command (START, STOP, WRITE, etc.)
            target: Target service or tag
            parameters: Command parameters
            result: Command result (SUCCESS, FAILED)
            error_message: Error message if command failed
        """
        async with self._session_factory() as session:
            log = CommandAuditLog(
                timestamp=timestamp,
                command_type=command_type,
                target=target,
                parameters=parameters,
                result=result,
                error_message=error_message,
            )
            session.add(log)
            await session.commit()

    async def get_audit_log(
        self,
        start: datetime,
        end: datetime,
    ) -> list[CommandAuditLog]:
        """Get command audit logs within time range.

        Args:
            start: Start of time range (inclusive)
            end: End of time range (inclusive)

        Returns:
            List of CommandAuditLog ordered by timestamp ascending
        """
        async with self._session_factory() as session:
            stmt = (
                select(CommandAuditLog)
                .where(
                    CommandAuditLog.timestamp >= start,
                    CommandAuditLog.timestamp <= end,
                )
                .order_by(CommandAuditLog.timestamp.asc())
            )
            result = await session.execute(stmt)
            logs = list(result.scalars().all())

            # Deserialize parameters JSON and restore timezone info
            for log in logs:
                if isinstance(log.parameters, str):
                    log.parameters = json.loads(log.parameters)
                # SQLite doesn't preserve timezone info, restore UTC
                if log.timestamp and log.timestamp.tzinfo is None:
                    log.timestamp = log.timestamp.replace(tzinfo=timezone.utc)

            return logs
