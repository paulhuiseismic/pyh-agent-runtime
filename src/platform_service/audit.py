"""用量/成本审计存储（SQLite，同 kernel.memory.storage.SqliteStore 风格：
单一共享连接 + asyncio.Lock 序列化写事务）。

契约见 specs/010-multitenant-audit/contracts/audit-api.md。
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime

import aiosqlite

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS audit_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    source TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost_usd REAL NOT NULL,
    status TEXT NOT NULL
)
"""
_CREATE_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_audit_entries_tenant_timestamp "
    "ON audit_entries (tenant_id, timestamp)"
)


@dataclass(frozen=True)
class AuditEntry:
    tenant_id: str
    source: str
    timestamp: datetime
    input_tokens: int
    output_tokens: int
    cost_usd: float
    status: str


@dataclass(frozen=True)
class UsageSummary:
    tenant_id: str
    start: datetime
    end: datetime
    request_count: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float


class AuditStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def _get_conn(self) -> aiosqlite.Connection:
        async with self._lock:
            if self._conn is None:
                self._conn = await aiosqlite.connect(self._db_path, isolation_level=None)
                await self._conn.execute("PRAGMA journal_mode=WAL")
                await self._conn.execute(_CREATE_TABLE_SQL)
                await self._conn.execute(_CREATE_INDEX_SQL)
            return self._conn

    async def record(self, entry: AuditEntry) -> None:
        conn = await self._get_conn()
        async with self._lock:
            await conn.execute(
                "INSERT INTO audit_entries "
                "(tenant_id, source, timestamp, input_tokens, output_tokens, "
                "cost_usd, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    entry.tenant_id,
                    entry.source,
                    entry.timestamp.isoformat(),
                    entry.input_tokens,
                    entry.output_tokens,
                    entry.cost_usd,
                    entry.status,
                ),
            )

    async def query_usage(
        self, tenant_id: str, start: datetime, end: datetime
    ) -> UsageSummary:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(input_tokens), 0), "
            "COALESCE(SUM(output_tokens), 0), COALESCE(SUM(cost_usd), 0) "
            "FROM audit_entries WHERE tenant_id = ? AND timestamp >= ? "
            "AND timestamp <= ?",
            (tenant_id, start.isoformat(), end.isoformat()),
        )
        row = await cursor.fetchone()
        request_count, total_input_tokens, total_output_tokens, total_cost_usd = row
        return UsageSummary(
            tenant_id=tenant_id,
            start=start,
            end=end,
            request_count=request_count,
            total_input_tokens=total_input_tokens,
            total_output_tokens=total_output_tokens,
            total_cost_usd=total_cost_usd,
        )

    async def sum_cost_since(self, tenant_id: str, since: datetime) -> float:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM audit_entries "
            "WHERE tenant_id = ? AND timestamp >= ?",
            (tenant_id, since.isoformat()),
        )
        (total,) = await cursor.fetchone()
        return total

    async def aclose(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
