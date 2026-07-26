"""kernel.memory 公共接口（契约见 specs/003 contracts/memory-api.md）。

Memory Protocol 签名冻结于 001，本 feature 不得修改。
"""

from typing import Protocol, runtime_checkable

from kernel.memory.compaction import compact_if_needed
from kernel.memory.models import ContextBudget
from kernel.memory.storage import SqliteStore
from kernel.provider import LLMProvider, Message


@runtime_checkable
class Memory(Protocol):
    async def load(self, session_id: str, *, tenant_id: str) -> list[Message]: ...

    async def append(
        self, session_id: str, message: Message, *, tenant_id: str
    ) -> None: ...


class SqliteMemory:
    def __init__(
        self,
        *,
        db_path: str,
        provider: LLMProvider,
        model: str,
        budget: ContextBudget = ContextBudget(),
    ) -> None:
        self._store = SqliteStore(db_path)
        self._provider = provider
        self._model = model
        self._budget = budget

    async def aclose(self) -> None:
        await self._store.close()

    async def append(self, session_id: str, message: Message, *, tenant_id: str) -> None:
        await self._store.append_row(tenant_id, session_id, message)
        await self._compact_if_needed(session_id, tenant_id=tenant_id)

    async def load(self, session_id: str, *, tenant_id: str) -> list[Message]:
        await self._compact_if_needed(session_id, tenant_id=tenant_id)
        rows = await self._store.load_rows(tenant_id, session_id)
        return [row.message for row in rows]

    async def _compact_if_needed(self, session_id: str, *, tenant_id: str) -> None:
        # FR-004/research.md R6：append 与 load 共用同一压缩判定，均基于
        # "读取当前全部消息后检查预算"。
        rows = await self._store.load_rows(tenant_id, session_id)
        result = await compact_if_needed(
            rows, self._budget, self._provider, self._model, tenant_id=tenant_id
        )
        if result is None:
            return
        seqs_to_remove, summary_message = result
        # provider 调用已在 compact_if_needed 内成功完成，此处只做存储层的
        # 原子替换；若 provider 调用失败会在上一步直接上抛，不会执行到这里，
        # 原始数据因而不受影响（FR-007，research.md R5）
        await self._store.replace_rows(tenant_id, session_id, seqs_to_remove, summary_message)


class NoopMemory:
    """占位实现（001 交付，保留供未启用持久化的场景使用）。"""

    async def load(self, session_id: str, *, tenant_id: str) -> list[Message]:
        return []

    async def append(
        self, session_id: str, message: Message, *, tenant_id: str
    ) -> None:
        return None


__all__ = ["Memory", "SqliteMemory", "NoopMemory", "ContextBudget"]
