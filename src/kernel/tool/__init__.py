"""tool 模块接口骨架（插件机制与沙箱执行属 feature 004）。

本接口不含沙箱语义：沙箱是 invoke() 背后的执行环境实现，
不改变接口契约（见 specs/001 spec.md Assumptions）。
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class Tool(Protocol):
    name: str
    description: str

    async def invoke(self, arguments: dict, *, tenant_id: str) -> str: ...


class EchoTool:
    """占位实现：原样返回入参，仅锁定接口签名。"""

    name = "echo"
    description = "占位工具：原样返回 arguments 的字符串表示"

    async def invoke(self, arguments: dict, *, tenant_id: str) -> str:
        return str(arguments)


__all__ = ["Tool", "EchoTool"]
