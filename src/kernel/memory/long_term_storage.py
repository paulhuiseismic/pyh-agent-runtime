"""长期记忆 SQLite 存储层：memory_entries 表增删查（见 specs/004 data-model.md，research.md R3）。

独立于 003 的 messages 表，不共享代码路径（FR-012）。写事务复用同一套
asyncio.Lock 序列化模式，理由与 003 storage.py 相同（共享单一连接，避免
并发协程打断 SQLite 事务边界）。
"""

import asyncio

import aiosqlite

from kernel.memory.long_term_models import MemoryEntry

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS memory_entries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id  TEXT NOT NULL,
    category   TEXT,
    content    TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (tenant_id, category)
)
"""


class LongTermStore:
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    async def _get_conn(self) -> aiosqlite.Connection:
        async with self._write_lock:
            if self._conn is None:
                self._conn = await aiosqlite.connect(self._db_path, isolation_level=None)
                await self._conn.execute("PRAGMA journal_mode=WAL")
                await self._conn.execute(_CREATE_TABLE_SQL)
            return self._conn

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def upsert_entries(self, tenant_id: str, entries: list[MemoryEntry]) -> None:
        if not entries:
            return
        conn = await self._get_conn()
        async with self._write_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                for entry in entries:
                    await conn.execute(
                        "INSERT INTO memory_entries (tenant_id, category, content, updated_at) "
                        "VALUES (?, ?, ?, datetime('now')) "
                        "ON CONFLICT(tenant_id, category) DO UPDATE SET "
                        "content = excluded.content, updated_at = excluded.updated_at",
                        (tenant_id, entry.category, entry.content),
                    )
                await conn.commit()
            except BaseException:
                await conn.rollback()
                raise

    async def query_entries(self, tenant_id: str, limit: int) -> list[MemoryEntry]:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT content, category FROM memory_entries "
            "WHERE tenant_id = ? ORDER BY updated_at DESC, id DESC LIMIT ?",
            (tenant_id, limit),
        )
        rows = await cursor.fetchall()
        return [MemoryEntry(content=content, category=category) for content, category in rows]
