"""memory 模块接口骨架（压缩与上下文管理属 feature 003）。

所有操作必带 tenant_id——多租户隔离键（宪法附加约束）；
存储实现由平台层注入，内核只定义接口。
"""

from typing import Protocol, runtime_checkable

from kernel.provider.models import Message


@runtime_checkable
class Memory(Protocol):
    async def load(self, session_id: str, *, tenant_id: str) -> list[Message]: ...

    async def append(
        self, session_id: str, message: Message, *, tenant_id: str
    ) -> None: ...


class NoopMemory:
    """占位实现：不持久化任何内容，仅锁定接口签名。"""

    async def load(self, session_id: str, *, tenant_id: str) -> list[Message]:
        return []

    async def append(
        self, session_id: str, message: Message, *, tenant_id: str
    ) -> None:
        return None


__all__ = ["Memory", "NoopMemory"]
