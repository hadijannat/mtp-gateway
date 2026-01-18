"""SQLAlchemy ORM models for persistence layer.

Defines database models for service state snapshots, tag value history,
and command audit logging. Uses SQLAlchemy 2.0 declarative style.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


class ServiceStateSnapshot(Base):
    """Persisted service state for crash recovery.

    Stores the runtime state of a service so it can be restored
    after a gateway restart.

    Attributes:
        id: Auto-incrementing primary key
        service_name: Unique service identifier
        state: PackML state name (e.g., "EXECUTE", "IDLE")
        procedure_id: Active procedure ID, or None
        parameters: JSON-serialized procedure parameters
        started_at: When the service was started
        updated_at: Last state update timestamp
    """

    __tablename__ = "service_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service_name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    state: Mapped[str] = mapped_column(String(50))
    procedure_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parameters: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __init__(
        self,
        service_name: str,
        state: str,
        procedure_id: int | None = None,
        parameters: dict[str, Any] | None = None,
        started_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        """Initialize ServiceStateSnapshot.

        Args:
            service_name: Unique service identifier
            state: PackML state name
            procedure_id: Active procedure ID
            parameters: Procedure parameters as dict (serialized to JSON internally)
            started_at: When service was started
            updated_at: Last update timestamp
        """
        self.service_name = service_name
        self.state = state
        self.procedure_id = procedure_id
        self.parameters = json.dumps(parameters) if parameters else None
        self.started_at = started_at or datetime.now(timezone.utc)
        self.updated_at = updated_at or datetime.now(timezone.utc)


class TagValueRecord(Base):
    """Historical tag values for time-series queries.

    Stores tag values over time for trend analysis and debugging.
    Values are stored as JSON to support multiple data types.

    Attributes:
        id: Auto-incrementing primary key
        tag_name: Tag identifier
        value: Tag value (stored as JSON-compatible type)
        quality: OPC UA quality string (e.g., "GOOD", "BAD")
        timestamp: When the value was recorded by the gateway
        source_timestamp: Original timestamp from the source (PLC)
    """

    __tablename__ = "tag_values"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tag_name: Mapped[str] = mapped_column(String(255), index=True)
    value: Mapped[Any] = mapped_column(Text)  # JSON serialized
    quality: Mapped[str] = mapped_column(String(50))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __init__(
        self,
        tag_name: str,
        value: float | int | bool | str,
        quality: str,
        timestamp: datetime,
        source_timestamp: datetime | None = None,
    ) -> None:
        """Initialize TagValueRecord.

        Args:
            tag_name: Tag identifier
            value: Tag value
            quality: OPC UA quality string
            timestamp: Gateway timestamp
            source_timestamp: Source timestamp from PLC
        """
        self.tag_name = tag_name
        self.value = value
        self.quality = quality
        self.timestamp = timestamp
        self.source_timestamp = source_timestamp


class CommandAuditLog(Base):
    """Audit trail for all commands.

    Records every command sent through the gateway for compliance
    and debugging purposes.

    Attributes:
        id: Auto-incrementing primary key
        timestamp: When the command was issued
        command_type: Type of command (START, STOP, WRITE, etc.)
        target: Target service or tag
        parameters: JSON-serialized command parameters
        result: Command result (SUCCESS, FAILED)
        error_message: Error message if command failed
    """

    __tablename__ = "command_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    command_type: Mapped[str] = mapped_column(String(50))
    target: Mapped[str] = mapped_column(String(255))
    parameters: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __init__(
        self,
        timestamp: datetime,
        command_type: str,
        target: str,
        parameters: dict[str, Any] | None = None,
        result: str = "SUCCESS",
        error_message: str | None = None,
    ) -> None:
        """Initialize CommandAuditLog.

        Args:
            timestamp: When the command was issued
            command_type: Type of command
            target: Target service or tag
            parameters: Command parameters (serialized to JSON internally)
            result: Command result
            error_message: Error message if failed
        """
        self.timestamp = timestamp
        self.command_type = command_type
        self.target = target
        self.parameters = json.dumps(parameters) if parameters else None
        self.result = result
        self.error_message = error_message
