"""Tool Protocol（001/002 已冻结签名，见 specs/001 spec.md Assumptions）。"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class Tool(Protocol):
    name: str
    description: str

    async def invoke(self, arguments: dict, *, tenant_id: str) -> str: ...
