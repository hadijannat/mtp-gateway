"""Audit trail for service commands and state transitions.

Provides comprehensive logging of all service operations for
debugging, compliance, and operational visibility.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from mtp_gateway.domain.state_machine.packml import (
        PackMLCommand,
        PackMLState,
        TransitionResult,
    )

logger = structlog.get_logger(__name__)

# Keys that should not be logged (contain sensitive values)
_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "secret",
        "token",
        "key",
        "api_key",
        "apikey",
        "credential",
        "private",
    }
)


def _is_sensitive(key: str) -> bool:
    """Check if a key name suggests sensitive content."""
    key_lower = key.lower()
    return any(sensitive in key_lower for sensitive in _SENSITIVE_KEYS)


@dataclass
class AuditEntry:
    """Base class for audit entries.

    Attributes:
        timestamp: When the event occurred.
        service: Name of the service.
    """

    service: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class CommandAuditEntry(AuditEntry):
    """Audit entry for service commands.

    Records every command sent to a service, including the source,
    result, and optional procedure ID.

    Attributes:
        command: The PackML command that was sent.
        source: Origin of the command (e.g., "user", "completion_monitor").
        result: The TransitionResult from executing the command.
        procedure_id: Optional procedure ID for START commands.
    """

    command: PackMLCommand = field(default=None)  # type: ignore[assignment]
    source: str = ""
    result: TransitionResult = field(default=None)  # type: ignore[assignment]
    procedure_id: int | None = None


@dataclass
class StateTransitionAuditEntry(AuditEntry):
    """Audit entry for state transitions.

    Records every state transition, including the trigger reason.

    Attributes:
        from_state: State before the transition.
        to_state: State after the transition.
        trigger: What caused the transition (e.g., "START command", "auto-complete").
    """

    from_state: PackMLState = field(default=None)  # type: ignore[assignment]
    to_state: PackMLState = field(default=None)  # type: ignore[assignment]
    trigger: str = ""


@dataclass
class SecurityAuditEntry(AuditEntry):
    """Audit entry for security events.

    Records security-relevant events such as certificate generation,
    authentication attempts, and secret access.

    Attributes:
        event_type: Type of security event.
        details: Event-specific details (sensitive values are masked).
        success: Whether the operation succeeded.
        source_ip: Optional source IP address for network events.
    """

    event_type: str = ""
    details: dict[str, object] = field(default_factory=dict)
    success: bool = True
    source_ip: str | None = None


class AuditTrail:
    """Audit trail for service operations.

    Maintains an in-memory log of all commands and state transitions.
    The log can be filtered by service and is limited to prevent
    unbounded memory growth.

    Example:
        ```python
        audit = AuditTrail(max_entries=1000)

        await audit.log_command(
            service="Reactor",
            command=PackMLCommand.START,
            source="user",
            result=transition_result,
        )

        entries = audit.get_entries(service="Reactor")
        ```
    """

    def __init__(self, max_entries: int = 10000) -> None:
        """Initialize the audit trail.

        Args:
            max_entries: Maximum number of entries to retain.
                         Oldest entries are discarded when limit is reached.
        """
        self._max_entries = max_entries
        self._entries: deque[AuditEntry] = deque(maxlen=max_entries)
        self._lock = asyncio.Lock()

    async def log_command(
        self,
        service: str,
        command: PackMLCommand,
        source: str,
        result: TransitionResult,
        procedure_id: int | None = None,
    ) -> None:
        """Log a service command.

        Args:
            service: Name of the service.
            command: PackML command that was sent.
            source: Origin of the command (e.g., "user", "timer").
            result: TransitionResult from executing the command.
            procedure_id: Optional procedure ID for START commands.
        """
        entry = CommandAuditEntry(
            service=service,
            command=command,
            source=source,
            result=result,
            procedure_id=procedure_id,
        )

        async with self._lock:
            self._entries.append(entry)

        logger.debug(
            "Command logged",
            service=service,
            command=command.name,
            source=source,
            success=result.success,
            from_state=result.from_state.name if result.from_state else None,
            to_state=result.to_state.name if result.to_state else None,
        )

    async def log_state_transition(
        self,
        service: str,
        from_state: PackMLState,
        to_state: PackMLState,
        trigger: str,
    ) -> None:
        """Log a state transition.

        Args:
            service: Name of the service.
            from_state: State before the transition.
            to_state: State after the transition.
            trigger: What caused the transition.
        """
        entry = StateTransitionAuditEntry(
            service=service,
            from_state=from_state,
            to_state=to_state,
            trigger=trigger,
        )

        async with self._lock:
            self._entries.append(entry)

        logger.debug(
            "State transition logged",
            service=service,
            from_state=from_state.name,
            to_state=to_state.name,
            trigger=trigger,
        )

    async def log_security_event(
        self,
        event_type: str,
        *,
        service: str = "security",
        details: dict[str, object] | None = None,
        success: bool = True,
        source_ip: str | None = None,
    ) -> None:
        """Log a security event.

        Security events include:
        - cert_generated: Certificate was generated
        - cert_expired: Certificate expiry detected
        - cert_expiring_soon: Certificate will expire within 30 days
        - auth_success: Successful authentication
        - auth_failure: Failed authentication attempt
        - secret_accessed: Secret was retrieved
        - policy_changed: Security policy was modified

        Args:
            event_type: Type of security event.
            service: Service context (default: "security").
            details: Event-specific details (sensitive values should be masked).
            success: Whether the operation succeeded.
            source_ip: Optional source IP for network events.
        """
        entry = SecurityAuditEntry(
            service=service,
            event_type=event_type,
            details=details or {},
            success=success,
            source_ip=source_ip,
        )

        async with self._lock:
            self._entries.append(entry)

        # Log at appropriate level based on event type and success
        log_func = logger.warning if not success else logger.info
        log_func(
            "Security event",
            event_type=event_type,
            service=service,
            success=success,
            source_ip=source_ip,
            **{k: v for k, v in (details or {}).items() if not _is_sensitive(k)},
        )

    def get_entries(
        self,
        service: str | None = None,
        limit: int | None = None,
    ) -> list[AuditEntry]:
        """Get audit entries.

        Args:
            service: Filter by service name (optional).
            limit: Maximum number of entries to return (optional).

        Returns:
            List of audit entries in chronological order.
        """
        entries = list(self._entries)

        if service is not None:
            entries = [e for e in entries if e.service == service]

        if limit is not None:
            entries = entries[-limit:]

        return entries

    def clear(self) -> None:
        """Clear all audit entries."""
        self._entries.clear()
        logger.info("Audit trail cleared")

    @property
    def entry_count(self) -> int:
        """Get the current number of entries."""
        return len(self._entries)


__all__ = [
    "AuditEntry",
    "AuditTrail",
    "CommandAuditEntry",
    "SecurityAuditEntry",
    "StateTransitionAuditEntry",
]
