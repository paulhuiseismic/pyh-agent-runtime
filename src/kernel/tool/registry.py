"""工具注册中心（见 specs/005 data-model.md，research.md R6）。"""

from kernel.provider.errors import InvalidRequestError
from kernel.tool.protocol import Tool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise InvalidRequestError(f"工具名称 {tool.name!r} 已被注册，拒绝重复注册")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def as_dict(self) -> dict[str, Tool]:
        return dict(self._tools)
