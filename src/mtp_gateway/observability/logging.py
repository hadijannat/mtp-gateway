"""Logging configuration for MTP Gateway.

Uses structlog for structured logging with support for both
human-readable console output and JSON format for production.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

import structlog


def setup_logging(
    level: str | None = None,
    log_format: str | None = None,
) -> None:
    """Configure structured logging for the gateway.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR). Defaults to MTP_LOG_LEVEL env var
            or INFO.
        log_format: Output format ('console' or 'json'). Defaults to MTP_LOG_FORMAT env var
            or 'console'.
    """
    # Get settings from environment or parameters
    level = level or os.environ.get("MTP_LOG_LEVEL", "INFO")
    log_format = log_format or os.environ.get("MTP_LOG_FORMAT", "console")

    # Convert string level to logging constant
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    # Configure structlog processors
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if log_format == "json":
        # JSON format for production
        processors = [
            *shared_processors,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]
    else:
        # Console format for development
        processors = [
            *shared_processors,
            structlog.dev.ConsoleRenderer(
                colors=True,
                exception_formatter=structlog.dev.plain_traceback,
            ),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a logger instance.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Configured structlog logger
    """
    return structlog.get_logger(name)


class LogContext:
    """Context manager for adding context to log messages."""

    def __init__(self, **kwargs: Any) -> None:
        self._context = kwargs

    def __enter__(self) -> LogContext:
        structlog.contextvars.bind_contextvars(**self._context)
        return self

    def __exit__(self, *args: Any) -> None:
        structlog.contextvars.unbind_contextvars(*self._context.keys())
