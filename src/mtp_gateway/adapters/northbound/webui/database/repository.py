"""Repository pattern for database operations.

Provides type-safe CRUD operations for alarms and tag history.
Uses asyncpg for efficient PostgreSQL/TimescaleDB queries.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from asyncpg import Connection, Pool, Record

logger = structlog.get_logger(__name__)


@dataclass
class AlarmRecord:
    """Alarm data record from database."""

    id: int
    alarm_id: str
    source: str
    priority: int
    state: str
    message: str
    value: float | None
    raised_at: datetime
    acknowledged_at: datetime | None
    acknowledged_by: int | None
    acknowledged_by_username: str | None
    cleared_at: datetime | None
    shelved_until: datetime | None

    @classmethod
    def from_row(cls, row: Record) -> "AlarmRecord":
        """Create from database row."""
        return cls(
            id=row["id"],
            alarm_id=row["alarm_id"],
            source=row["source"],
            priority=row["priority"],
            state=row["state"],
            message=row["message"],
            value=row["value"],
            raised_at=row["raised_at"],
            acknowledged_at=row.get("acknowledged_at"),
            acknowledged_by=row.get("acknowledged_by"),
            acknowledged_by_username=row.get("username"),
            cleared_at=row.get("cleared_at"),
            shelved_until=row.get("shelved_until"),
        )


@dataclass
class HistoryRecord:
    """Tag history data point from database."""

    time: datetime
    tag_name: str
    value: float | None
    quality: str

    @classmethod
    def from_row(cls, row: Record) -> "HistoryRecord":
        """Create from database row."""
        return cls(
            time=row["time"] if isinstance(row["time"], datetime) else row["bucket"],
            tag_name=row["tag_name"],
            value=row["value"],
            quality=row["quality"],
        )


class AlarmRepository:
    """Repository for alarm CRUD operations.

    Provides ISA-18.2 compliant alarm management with proper
    state transitions and acknowledgment tracking.
    """

    def __init__(self, pool: Pool) -> None:
        """Initialize with connection pool.

        Args:
            pool: asyncpg connection pool
        """
        self._pool = pool

    async def get_all(
        self,
        state: str | None = None,
        priority: int | None = None,
        source: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[AlarmRecord], int, int, int]:
        """Get alarms with optional filtering.

        Args:
            state: Filter by state (active, acknowledged, cleared, shelved)
            priority: Filter by priority (1-4)
            source: Filter by source (partial match)
            since: Only alarms raised after this time
            limit: Maximum results
            offset: Results offset

        Returns:
            Tuple of (alarms, total_count, active_count, unacknowledged_count)
        """
        async with self._pool.acquire() as conn:
            # Build query with filters
            conditions = []
            params = []
            param_idx = 1

            if state:
                conditions.append(f"a.state = ${param_idx}")
                params.append(state)
                param_idx += 1

            if priority:
                conditions.append(f"a.priority = ${param_idx}")
                params.append(priority)
                param_idx += 1

            if source:
                conditions.append(f"a.source ILIKE ${param_idx}")
                params.append(f"%{source}%")
                param_idx += 1

            if since:
                conditions.append(f"a.raised_at >= ${param_idx}")
                params.append(since)
                param_idx += 1

            where_clause = " AND ".join(conditions) if conditions else "TRUE"

            # Main query with user join
            query = f"""
                SELECT a.*, u.username
                FROM alarms a
                LEFT JOIN users u ON a.acknowledged_by = u.id
                WHERE {where_clause}
                ORDER BY a.raised_at DESC
                LIMIT ${param_idx} OFFSET ${param_idx + 1}
            """
            params.extend([limit, offset])

            rows = await conn.fetch(query, *params)
            alarms = [AlarmRecord.from_row(row) for row in rows]

            # Count queries
            count_query = f"SELECT COUNT(*) FROM alarms a WHERE {where_clause}"
            count_params = params[:-2]  # Remove limit/offset
            total = await conn.fetchval(count_query, *count_params)

            active_count = await conn.fetchval(
                "SELECT COUNT(*) FROM alarms WHERE state IN ('active', 'acknowledged')"
            )
            unack_count = await conn.fetchval(
                "SELECT COUNT(*) FROM alarms WHERE state = 'active'"
            )

            return alarms, total, active_count, unack_count

    async def get_by_id(self, alarm_id: int) -> AlarmRecord | None:
        """Get a single alarm by database ID.

        Args:
            alarm_id: Alarm database ID

        Returns:
            Alarm record or None if not found
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT a.*, u.username
                FROM alarms a
                LEFT JOIN users u ON a.acknowledged_by = u.id
                WHERE a.id = $1
                """,
                alarm_id,
            )
            return AlarmRecord.from_row(row) if row else None

    async def create(
        self,
        alarm_id: str,
        source: str,
        priority: int,
        message: str,
        value: float | None = None,
    ) -> AlarmRecord:
        """Create a new alarm (raise alarm).

        Args:
            alarm_id: Logical alarm identifier
            source: Source data assembly or tag
            priority: Priority level (1-4)
            message: Alarm message
            value: Value that triggered alarm

        Returns:
            Created alarm record
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO alarms (alarm_id, source, priority, state, message, value)
                VALUES ($1, $2, $3, 'active', $4, $5)
                RETURNING *
                """,
                alarm_id,
                source,
                priority,
                message,
                value,
            )
            logger.info(
                "Alarm raised",
                alarm_id=alarm_id,
                source=source,
                priority=priority,
            )
            return AlarmRecord.from_row(row)

    async def acknowledge(
        self,
        alarm_id: int,
        user_id: int,
        username: str,
    ) -> AlarmRecord | None:
        """Acknowledge an active alarm.

        Args:
            alarm_id: Alarm database ID
            user_id: User ID who acknowledged
            username: Username for logging

        Returns:
            Updated alarm record or None if not found/invalid state
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE alarms
                SET state = 'acknowledged',
                    acknowledged_at = NOW(),
                    acknowledged_by = $2
                WHERE id = $1 AND state = 'active'
                RETURNING *
                """,
                alarm_id,
                user_id,
            )
            if row:
                logger.info(
                    "Alarm acknowledged",
                    alarm_id=alarm_id,
                    username=username,
                )
                # Re-fetch to get username joined
                return await self.get_by_id(alarm_id)
            return None

    async def clear(self, alarm_id: int, username: str) -> AlarmRecord | None:
        """Clear an acknowledged alarm.

        Args:
            alarm_id: Alarm database ID
            username: Username for logging

        Returns:
            Updated alarm record or None if not found/invalid state
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE alarms
                SET state = 'cleared',
                    cleared_at = NOW()
                WHERE id = $1 AND state = 'acknowledged'
                RETURNING *
                """,
                alarm_id,
            )
            if row:
                logger.info(
                    "Alarm cleared",
                    alarm_id=alarm_id,
                    username=username,
                )
                return await self.get_by_id(alarm_id)
            return None

    async def shelve(
        self,
        alarm_id: int,
        duration_minutes: int,
        reason: str,
        username: str,
    ) -> AlarmRecord | None:
        """Shelve an alarm temporarily.

        Args:
            alarm_id: Alarm database ID
            duration_minutes: Shelve duration
            reason: Reason for shelving
            username: Username for logging

        Returns:
            Updated alarm record or None if not found
        """
        shelved_until = datetime.now(UTC) + timedelta(minutes=duration_minutes)

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE alarms
                SET state = 'shelved',
                    shelved_until = $2
                WHERE id = $1 AND state IN ('active', 'acknowledged')
                RETURNING *
                """,
                alarm_id,
                shelved_until,
            )
            if row:
                logger.info(
                    "Alarm shelved",
                    alarm_id=alarm_id,
                    duration_minutes=duration_minutes,
                    reason=reason,
                    username=username,
                )
                return await self.get_by_id(alarm_id)
            return None

    async def unshelve_expired(self) -> int:
        """Unshelve alarms whose shelve period has expired.

        Returns:
            Number of alarms unshelved
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE alarms
                SET state = 'active',
                    shelved_until = NULL
                WHERE state = 'shelved'
                  AND shelved_until <= NOW()
                """
            )
            # Parse "UPDATE N" to get count
            count = int(result.split()[-1]) if result else 0
            if count > 0:
                logger.info("Unshelved expired alarms", count=count)
            return count

    async def auto_clear_if_condition_gone(
        self,
        alarm_id_pattern: str,
        source: str,
    ) -> AlarmRecord | None:
        """Auto-clear alarm if condition is no longer present.

        Used by AlarmDetector when monitored value returns to normal.

        Args:
            alarm_id_pattern: Alarm ID pattern to match
            source: Alarm source

        Returns:
            Cleared alarm record or None
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE alarms
                SET state = 'cleared',
                    cleared_at = NOW()
                WHERE alarm_id = $1 AND source = $2
                  AND state IN ('active', 'acknowledged')
                RETURNING *
                """,
                alarm_id_pattern,
                source,
            )
            if row:
                logger.info(
                    "Alarm auto-cleared (condition gone)",
                    alarm_id=alarm_id_pattern,
                    source=source,
                )
                return AlarmRecord.from_row(row)
            return None

    async def find_active_alarm(
        self,
        alarm_id: str,
        source: str,
    ) -> AlarmRecord | None:
        """Find an active alarm by alarm_id and source.

        Args:
            alarm_id: Logical alarm identifier
            source: Alarm source

        Returns:
            Active alarm record or None
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT a.*, u.username
                FROM alarms a
                LEFT JOIN users u ON a.acknowledged_by = u.id
                WHERE a.alarm_id = $1 AND a.source = $2
                  AND a.state IN ('active', 'acknowledged')
                """,
                alarm_id,
                source,
            )
            return AlarmRecord.from_row(row) if row else None


class HistoryRepository:
    """Repository for tag history operations.

    Provides efficient time-series queries using TimescaleDB's
    time_bucket aggregation for trending charts.
    """

    # Valid time bucket formats
    VALID_BUCKETS = {"1s", "5s", "10s", "30s", "1m", "5m", "15m", "30m", "1h", "4h", "1d"}

    def __init__(self, pool: Pool) -> None:
        """Initialize with connection pool.

        Args:
            pool: asyncpg connection pool
        """
        self._pool = pool

    def _parse_bucket_size(self, bucket: str) -> str:
        """Convert bucket size to PostgreSQL interval.

        Args:
            bucket: Bucket size (1s, 1m, 1h, 1d)

        Returns:
            PostgreSQL interval string

        Raises:
            ValueError: If invalid bucket format
        """
        if bucket not in self.VALID_BUCKETS:
            raise ValueError(f"Invalid bucket size: {bucket}. Valid: {self.VALID_BUCKETS}")

        # Parse number and unit
        unit = bucket[-1]
        value = bucket[:-1]

        unit_map = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}
        return f"{value} {unit_map[unit]}"

    async def insert(
        self,
        tag_name: str,
        value: float | None,
        quality: str,
        timestamp: datetime | None = None,
    ) -> None:
        """Insert a single history record.

        Args:
            tag_name: Tag name
            value: Tag value
            quality: Data quality (good, bad, uncertain)
            timestamp: Optional timestamp (defaults to now)
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO tag_history (time, tag_name, value, quality)
                VALUES ($1, $2, $3, $4)
                """,
                timestamp or datetime.now(UTC),
                tag_name,
                value,
                quality,
            )

    async def insert_batch(
        self,
        records: list[tuple[datetime, str, float | None, str]],
    ) -> int:
        """Insert multiple history records efficiently.

        Args:
            records: List of (timestamp, tag_name, value, quality) tuples

        Returns:
            Number of records inserted
        """
        if not records:
            return 0

        async with self._pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO tag_history (time, tag_name, value, quality)
                VALUES ($1, $2, $3, $4)
                """,
                records,
            )
            return len(records)

    async def query(
        self,
        tag_name: str,
        start_time: datetime,
        end_time: datetime,
        aggregate: str = "none",
        bucket_size: str = "1m",
        limit: int = 1000,
    ) -> list[HistoryRecord]:
        """Query tag history with optional aggregation.

        Args:
            tag_name: Tag to query
            start_time: Start of time range
            end_time: End of time range
            aggregate: Aggregation function (none, avg, min, max, sum, count, first, last)
            bucket_size: Time bucket for aggregation
            limit: Maximum data points

        Returns:
            List of history records
        """
        async with self._pool.acquire() as conn:
            if aggregate == "none":
                # Raw data query
                rows = await conn.fetch(
                    """
                    SELECT time, tag_name, value, quality
                    FROM tag_history
                    WHERE tag_name = $1 AND time BETWEEN $2 AND $3
                    ORDER BY time DESC
                    LIMIT $4
                    """,
                    tag_name,
                    start_time,
                    end_time,
                    limit,
                )
            else:
                # Aggregated query using time_bucket
                interval = self._parse_bucket_size(bucket_size)
                agg_func = self._get_aggregate_sql(aggregate)

                rows = await conn.fetch(
                    f"""
                    SELECT
                        time_bucket('{interval}', time) AS bucket,
                        tag_name,
                        {agg_func}(value) AS value,
                        MODE() WITHIN GROUP (ORDER BY quality) AS quality
                    FROM tag_history
                    WHERE tag_name = $1 AND time BETWEEN $2 AND $3
                    GROUP BY bucket, tag_name
                    ORDER BY bucket DESC
                    LIMIT $4
                    """,
                    tag_name,
                    start_time,
                    end_time,
                    limit,
                )

            return [HistoryRecord.from_row(row) for row in rows]

    async def query_multi(
        self,
        tag_names: list[str],
        start_time: datetime,
        end_time: datetime,
        aggregate: str = "avg",
        bucket_size: str = "1m",
        limit: int = 1000,
    ) -> dict[str, list[HistoryRecord]]:
        """Query multiple tags with aggregation.

        Args:
            tag_names: Tags to query (max 10)
            start_time: Start of time range
            end_time: End of time range
            aggregate: Aggregation function
            bucket_size: Time bucket for aggregation
            limit: Maximum data points per tag

        Returns:
            Dict mapping tag names to history records
        """
        if len(tag_names) > 10:
            raise ValueError("Maximum 10 tags per query")

        async with self._pool.acquire() as conn:
            interval = self._parse_bucket_size(bucket_size)
            agg_func = self._get_aggregate_sql(aggregate)

            rows = await conn.fetch(
                f"""
                SELECT
                    time_bucket('{interval}', time) AS bucket,
                    tag_name,
                    {agg_func}(value) AS value,
                    MODE() WITHIN GROUP (ORDER BY quality) AS quality
                FROM tag_history
                WHERE tag_name = ANY($1) AND time BETWEEN $2 AND $3
                GROUP BY bucket, tag_name
                ORDER BY tag_name, bucket DESC
                """,
                tag_names,
                start_time,
                end_time,
            )

            # Group by tag name
            result: dict[str, list[HistoryRecord]] = {name: [] for name in tag_names}
            for row in rows:
                record = HistoryRecord.from_row(row)
                if record.tag_name in result:
                    if len(result[record.tag_name]) < limit:
                        result[record.tag_name].append(record)

            return result

    def _get_aggregate_sql(self, aggregate: str) -> str:
        """Get SQL aggregate function.

        Args:
            aggregate: Aggregate name

        Returns:
            SQL aggregate function

        Raises:
            ValueError: If invalid aggregate
        """
        agg_map = {
            "avg": "AVG",
            "min": "MIN",
            "max": "MAX",
            "sum": "SUM",
            "count": "COUNT",
            "first": "FIRST",
            "last": "LAST",
        }
        if aggregate not in agg_map:
            raise ValueError(f"Invalid aggregate: {aggregate}")
        return agg_map[aggregate]

    async def get_latest(self, tag_name: str) -> HistoryRecord | None:
        """Get the latest history record for a tag.

        Args:
            tag_name: Tag name

        Returns:
            Latest record or None
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT time, tag_name, value, quality
                FROM tag_history
                WHERE tag_name = $1
                ORDER BY time DESC
                LIMIT 1
                """,
                tag_name,
            )
            return HistoryRecord.from_row(row) if row else None

    async def get_available_tags(self) -> list[str]:
        """Get list of tags with history data.

        Returns:
            List of tag names
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT tag_name
                FROM tag_history
                ORDER BY tag_name
                """
            )
            return [row["tag_name"] for row in rows]
