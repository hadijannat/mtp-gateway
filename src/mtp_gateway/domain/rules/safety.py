"""Safety enforcement rules for MTP Gateway.

Provides safety controls for write operations:
- Write allowlist: Only allow writes to explicitly permitted tags
- Rate limiting: Token bucket algorithm to prevent write floods
- Safe state outputs: Values to write during emergency stop

These safety controls are CRITICAL for industrial safety compliance.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mtp_gateway.config.schema import SafetyConfig


def parse_rate_string(rate_str: str) -> float:
    """Parse a rate limit string into max operations per second.

    Supports formats:
    - "10/s" → 10 per second
    - "60/m" → 60 per minute → 1 per second
    - "3600/h" → 3600 per hour → 1 per second

    Args:
        rate_str: Rate string like "10/s", "60/m", "3600/h"

    Returns:
        Maximum operations per second as float

    Raises:
        ValueError: If format is invalid or rate is non-positive
    """
    pattern = r"^(-?[\d.]+)/([smh])$"
    match = re.match(pattern, rate_str.strip())

    if not match:
        raise ValueError(
            "Invalid rate format: "
            f"'{rate_str}'. Expected format like '10/s', '60/m', '3600/h'"
        )

    value = float(match.group(1))
    unit = match.group(2)

    if value <= 0:
        raise ValueError(f"Rate must be positive, got {value}")

    # Convert to per-second
    multipliers = {
        "s": 1.0,
        "m": 60.0,
        "h": 3600.0,
    }

    return value / multipliers[unit]


@dataclass(frozen=True)
class WriteValidation:
    """Result of write validation.

    Attributes:
        allowed: Whether the write is permitted
        reason: Explanation if write was denied
    """

    allowed: bool
    reason: str | None = None


@dataclass
class RateLimiter:
    """Token bucket rate limiter for write operations.

    Implements token bucket algorithm where:
    - Bucket fills at max_per_second rate
    - Each write consumes one token
    - If no token available, write is denied
    - Allows bursts up to bucket capacity

    Attributes:
        max_per_second: Maximum operations per second (also bucket capacity)
    """

    max_per_second: float
    _tokens: float = field(init=False)
    _last_refill: float = field(init=False)

    def __post_init__(self) -> None:
        """Initialize token bucket state."""
        self._tokens = 1.0  # Start with one token available
        self._last_refill = time.monotonic()

    def try_acquire(self) -> bool:
        """Attempt to acquire a token for a write operation.

        Refills tokens based on elapsed time since last refill,
        then attempts to consume one token.

        Returns:
            True if token acquired (write allowed), False otherwise
        """
        now = time.monotonic()
        elapsed = now - self._last_refill

        # Refill tokens based on elapsed time
        self._tokens = min(
            self._tokens + elapsed * self.max_per_second,
            self.max_per_second,  # Cap at bucket capacity
        )
        self._last_refill = now

        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True

        return False

    @classmethod
    def from_rate_string(cls, rate_str: str) -> RateLimiter:
        """Create RateLimiter from rate string.

        Args:
            rate_str: Rate string like "10/s"

        Returns:
            Configured RateLimiter instance
        """
        return cls(max_per_second=parse_rate_string(rate_str))


@dataclass
class SafetyController:
    """Enforces safety rules for write operations.

    Central safety enforcement point that validates all write operations
    against configured safety rules:
    - Allowlist: Only tags in allowlist can be written
    - Rate limit: Prevent write floods via token bucket
    - Safe state: Provide values for emergency stop

    Attributes:
        write_allowlist: Set of tag names allowed for writing
        safe_state_outputs: Tuple of (tag_name, safe_value) pairs
        rate_limiter: Optional rate limiter for write operations
    """

    write_allowlist: frozenset[str]
    safe_state_outputs: tuple[tuple[str, Any], ...]
    rate_limiter: RateLimiter | None

    def validate_write(self, tag_name: str) -> WriteValidation:
        """Validate if a write to a tag is allowed.

        Checks tag against the write allowlist. Rate limiting is
        checked separately via check_rate_limit().

        Args:
            tag_name: Name of tag to write

        Returns:
            WriteValidation indicating if write is permitted
        """
        if tag_name not in self.write_allowlist:
            return WriteValidation(
                allowed=False,
                reason=f"Tag '{tag_name}' not in write allowlist",
            )

        return WriteValidation(allowed=True)

    def check_rate_limit(self) -> bool:
        """Check if write is allowed by rate limiter.

        Returns:
            True if within rate limit (or no limiter configured),
            False if rate limit exceeded
        """
        if self.rate_limiter is None:
            return True

        return self.rate_limiter.try_acquire()

    def get_safe_state_values(self) -> dict[str, Any]:
        """Get safe state output values for emergency stop.

        Returns:
            Dictionary mapping tag names to their safe values
        """
        return dict(self.safe_state_outputs)

    @classmethod
    def from_config(cls, config: SafetyConfig) -> SafetyController:
        """Create SafetyController from SafetyConfig.

        Args:
            config: SafetyConfig from YAML configuration

        Returns:
            Configured SafetyController instance
        """
        # Build write allowlist as frozenset
        allowlist = frozenset(config.write_allowlist)

        # Build safe state outputs as tuple of tuples
        safe_outputs = tuple(
            (output.tag, output.value)
            for output in config.safe_state_outputs
        )

        # Create rate limiter if configured
        rate_limiter = None
        if config.command_rate_limit:
            rate_limiter = RateLimiter.from_rate_string(config.command_rate_limit)

        return cls(
            write_allowlist=allowlist,
            safe_state_outputs=safe_outputs,
            rate_limiter=rate_limiter,
        )
