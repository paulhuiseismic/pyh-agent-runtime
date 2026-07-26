"""SQLite 存储层：表结构、增删查（见 specs/003 data-model.md 表结构，research.md R2/R3）。

所有实例共享同一个 aiosqlite 连接（避免多连接的文件锁竞争开销），因此
"事务不可并发交错"这条约束由本类维护的 asyncio.Lock 保证——SQLite 的
BEGIN IMMEDIATE 语义假设每个逻辑事务独占连接直到提交，多协程并发调用
同一连接的 execute() 会打断这一假设（同一连接同一时刻只能有一个未提交
事务），故需要一把进程内锁序列化写事务；这不是引入分布式锁，只是让
"同一连接同一时刻只处理一个事务"这条已有的 SQLite 约束在协程层面成立。
"""

import asyncio

import aiosqlite

from kernel.provider.models import Message

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS messages (
    tenant_id  TEXT NOT NULL,
    session_id TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (tenant_id, session_id, seq)
)
"""


class StoredMessage:
    __slots__ = ("seq", "message")

    def __init__(self, seq: int, message: Message):
        self.seq = seq
        self.message = message


class SqliteStore:
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    async def _get_conn(self) -> aiosqlite.Connection:
        # 连接创建本身也需在锁内完成，避免并发协程同时执行 PRAGMA/建表语句
        # 竞态（曾触发 aiosqlite 后台线程死锁，见 research.md R3 的锁必要性说明）
        async with self._write_lock:
            if self._conn is None:
                # isolation_level=None: 关闭 sqlite3 模块的隐式事务管理，
                # 避免与本类显式的 BEGIN IMMEDIATE/COMMIT 冲突
                self._conn = await aiosqlite.connect(self._db_path, isolation_level=None)
                await self._conn.execute("PRAGMA journal_mode=WAL")
                await self._conn.execute(_CREATE_TABLE_SQL)
            return self._conn

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def append_row(self, tenant_id: str, session_id: str, message: Message) -> None:
        conn = await self._get_conn()
        # 事务内 SELECT MAX(seq)+1 后 INSERT，asyncio.Lock 保证同一连接上
        # 事务不被其他协程打断（research.md R3；锁的必要性见本文件顶部说明）
        async with self._write_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                cursor = await conn.execute(
                    "SELECT COALESCE(MAX(seq), -1) FROM messages WHERE tenant_id = ? AND session_id = ?",
                    (tenant_id, session_id),
                )
                (max_seq,) = await cursor.fetchone()
                next_seq = max_seq + 1
                await conn.execute(
                    "INSERT INTO messages (tenant_id, session_id, seq, role, content, created_at) "
                    "VALUES (?, ?, ?, ?, ?, datetime('now'))",
                    (tenant_id, session_id, next_seq, message.role, message.content),
                )
                await conn.commit()
            except BaseException:
                await conn.rollback()
                raise

    async def load_rows(self, tenant_id: str, session_id: str) -> list[StoredMessage]:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT seq, role, content FROM messages "
            "WHERE tenant_id = ? AND session_id = ? ORDER BY seq ASC",
            (tenant_id, session_id),
        )
        rows = await cursor.fetchall()
        return [
            StoredMessage(seq=seq, message=Message(role=role, content=content))
            for seq, role, content in rows
        ]

    async def replace_rows(
        self,
        tenant_id: str,
        session_id: str,
        seqs_to_remove: list[int],
        new_message: Message,
    ) -> None:
        """删除指定 seq 集合并插入一条新消息（摘要），同一事务保证原子性（research.md R5）。"""
        conn = await self._get_conn()
        async with self._write_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                placeholders = ",".join("?" for _ in seqs_to_remove)
                await conn.execute(
                    f"DELETE FROM messages WHERE tenant_id = ? AND session_id = ? "
                    f"AND seq IN ({placeholders})",
                    (tenant_id, session_id, *seqs_to_remove),
                )
                min_seq = min(seqs_to_remove)
                await conn.execute(
                    "INSERT INTO messages (tenant_id, session_id, seq, role, content, created_at) "
                    "VALUES (?, ?, ?, ?, ?, datetime('now'))",
                    (tenant_id, session_id, min_seq, new_message.role, new_message.content),
                )
                await conn.commit()
            except BaseException:
                await conn.rollback()
                raise
