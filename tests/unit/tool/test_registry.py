"""T011 [US1]: 工具注册中心——注册/查找/列出、重名拒绝、未找到不报错。"""

import pytest

from kernel.provider.errors import InvalidRequestError
from kernel.tool import EchoTool
from kernel.tool.registry import ToolRegistry


class StubTool:
    def __init__(self, name: str):
        self.name = name
        self.description = f"stub {name}"

    async def invoke(self, arguments: dict, *, tenant_id: str) -> str:
        return "stub result"


def test_register_and_find_by_name():
    registry = ToolRegistry()
    tool = StubTool("search")
    registry.register(tool)

    assert registry.get("search") is tool
    assert tool in registry.list_tools()


def test_duplicate_name_registration_rejected():
    registry = ToolRegistry()
    registry.register(StubTool("search"))
    original = registry.get("search")

    with pytest.raises(InvalidRequestError):
        registry.register(StubTool("search"))

    assert registry.get("search") is original  # 原有工具保持不变


def test_trusted_and_sandboxed_tools_coexist():
    registry = ToolRegistry()
    trusted = EchoTool()
    sandboxed = StubTool("sandbox-tool")
    registry.register(trusted)
    registry.register(sandboxed)

    assert registry.get("echo") is trusted
    assert registry.get("sandbox-tool") is sandboxed
    assert set(registry.list_tools()) == {trusted, sandboxed}


def test_lookup_unregistered_name_returns_none():
    registry = ToolRegistry()
    assert registry.get("does-not-exist") is None


def test_as_dict_produces_react_engine_compatible_view():
    registry = ToolRegistry()
    tool = StubTool("search")
    registry.register(tool)

    view = registry.as_dict()
    assert view == {"search": tool}
