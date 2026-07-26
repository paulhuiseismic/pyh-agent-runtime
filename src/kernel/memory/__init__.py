"""kernel.memory 公共接口（契约见 specs/003 contracts/memory-api.md）。

Memory Protocol 签名冻结于 001，本 feature 不得修改。
"""

from typing import Protocol, runtime_checkable

from kernel.provider import LLMProvider, Message
from kernel.memory.models import ContextBudget
from kernel.memory.storage import SqliteStore


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

    async def load(self, session_id: str, *, tenant_id: str) -> list[Message]:
        rows = await self._store.load_rows(tenant_id, session_id)
        return [row.message for row in rows]


class NoopMemory:
    """占位实现（001 交付，保留供未启用持久化的场景使用）。"""

    async def load(self, session_id: str, *, tenant_id: str) -> list[Message]:
        return []

    async def append(
        self, session_id: str, message: Message, *, tenant_id: str
    ) -> None:
        return None


__all__ = ["Memory", "SqliteMemory", "NoopMemory", "ContextBudget"]
