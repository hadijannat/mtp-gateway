"""Database connection pool for TimescaleDB.

Uses asyncpg for high-performance async PostgreSQL access.
Pool management follows FastAPI's lifespan pattern.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

import structlog

if TYPE_CHECKING:
    from asyncpg import Connection, Pool

logger = structlog.get_logger(__name__)

# Global pool reference - initialized by server lifespan
_pool: Pool | None = None


class DatabasePool:
    """Async database connection pool wrapper.

    Manages the asyncpg pool lifecycle and provides connection
    acquisition for repositories.

    Example:
        async with DatabasePool(url) as pool:
            async with pool.acquire() as conn:
                await conn.fetch("SELECT * FROM alarms")
    """

    def __init__(
        self,
        database_url: str,
        min_size: int = 2,
        max_size: int = 10,
    ) -> None:
        """Initialize pool configuration.

        Args:
            database_url: PostgreSQL connection string
            min_size: Minimum pool connections
            max_size: Maximum pool connections
        """
        self._database_url = database_url
        self._min_size = min_size
        self._max_size = max_size
        self._pool: Pool | None = None

    async def start(self) -> None:
        """Create and initialize the connection pool."""
        if self._pool is not None:
            return

        try:
            import asyncpg

            # Parse URL and create pool
            self._pool = await asyncpg.create_pool(
                self._database_url,
                min_size=self._min_size,
                max_size=self._max_size,
                command_timeout=30,
            )
            logger.info(
                "Database pool created",
                min_size=self._min_size,
                max_size=self._max_size,
            )
        except Exception as e:
            logger.error("Failed to create database pool", error=str(e))
            raise

    async def stop(self) -> None:
        """Close all pool connections."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("Database pool closed")

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[Connection]:
        """Acquire a connection from the pool.

        Yields:
            Database connection

        Raises:
            RuntimeError: If pool not initialized
        """
        if self._pool is None:
            raise RuntimeError("Database pool not initialized")

        async with self._pool.acquire() as conn:
            yield conn

    @property
    def pool(self) -> Pool | None:
        """Get the underlying asyncpg pool."""
        return self._pool

    @property
    def is_connected(self) -> bool:
        """Check if pool is initialized and connected."""
        return self._pool is not None

    async def __aenter__(self) -> "DatabasePool":
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type: type, exc_val: Exception, exc_tb: object) -> None:
        """Async context manager exit."""
        await self.stop()


def set_db_pool(pool: DatabasePool | None) -> None:
    """Set the global database pool reference.

    Called by server lifespan to make pool available for
    dependency injection.

    Args:
        pool: Database pool instance or None to clear
    """
    global _pool
    _pool = pool._pool if pool else None


def get_db_pool() -> Pool:
    """Get the global database pool.

    Used by FastAPI dependencies to inject pool into handlers.

    Returns:
        asyncpg pool instance

    Raises:
        RuntimeError: If pool not initialized
    """
    if _pool is None:
        raise RuntimeError("Database pool not initialized")
    return _pool
