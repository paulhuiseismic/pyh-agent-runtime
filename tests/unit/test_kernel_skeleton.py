"""T023 [US4]: 四模块可实例化、Protocol 结构检查、零平台层依赖（SC-005）。"""

import ast
from pathlib import Path

import pytest

from kernel.memory import Memory, NoopMemory
from kernel.provider import InvalidRequestError, LLMProvider, Message, PriceTable
from kernel.react import ReactLoop, SingleShotReactLoop
from kernel.tool import EchoTool, Tool

KERNEL_SRC = Path(__file__).resolve().parents[2] / "src" / "kernel"

# 内核只允许 import 标准库、kernel 自身与这些第三方库（plan.md 技术上下文）
ALLOWED_THIRD_PARTY = {"httpx", "opentelemetry"}
# 平台层/厂商 SDK 的禁止清单（零依赖断言的显式黑名单示例）
FORBIDDEN_PREFIXES = ("platform_", "openai", "anthropic", "litellm", "langfuse")


class TestInstantiation:
    def test_all_placeholder_implementations_instantiate(self):
        assert isinstance(NoopMemory(), Memory)
        assert isinstance(SingleShotReactLoop(), ReactLoop)
        assert isinstance(EchoTool(), Tool)

    async def test_react_placeholder_runs(self):
        result = await SingleShotReactLoop().run(
            "test goal", tenant_id="tenant-a", max_steps=5
        )
        assert "placeholder" in result

    async def test_memory_placeholder_roundtrip(self):
        memory = NoopMemory()
        await memory.append(
            "s1", Message(role="user", content="hi"), tenant_id="tenant-a"
        )
        assert await memory.load("s1", tenant_id="tenant-a") == []

    async def test_tool_placeholder_invokes(self):
        result = await EchoTool().invoke({"k": "v"}, tenant_id="tenant-a")
        assert result == "{'k': 'v'}"


class TestMaxStepsGuard:
    @pytest.mark.parametrize("max_steps", [0, -1])
    async def test_non_positive_max_steps_rejected(self, max_steps):
        with pytest.raises(InvalidRequestError):
            await SingleShotReactLoop().run(
                "goal", tenant_id="tenant-a", max_steps=max_steps
            )

    async def test_missing_tenant_rejected(self):
        with pytest.raises(InvalidRequestError):
            await SingleShotReactLoop().run("goal", tenant_id=" ", max_steps=5)


class TestNoPlatformDependency:
    """SC-005: 遍历 kernel 源文件，静态断言无平台层/厂商 SDK import。"""

    def _iter_imports(self):
        for py_file in KERNEL_SRC.rglob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        yield py_file, alias.name
                elif isinstance(node, ast.ImportFrom) and node.module:
                    yield py_file, node.module

    def test_kernel_has_zero_platform_dependencies(self):
        import sys

        stdlib = sys.stdlib_module_names
        violations = []
        for py_file, module in self._iter_imports():
            top = module.split(".")[0]
            if top == "kernel" or top in stdlib:
                continue
            if top in ALLOWED_THIRD_PARTY:
                continue
            violations.append(f"{py_file.name}: import {module}")
        assert violations == [], f"内核出现越界依赖: {violations}"

    def test_forbidden_modules_absent(self):
        for _, module in self._iter_imports():
            assert not module.startswith(FORBIDDEN_PREFIXES), (
                f"内核禁止依赖平台层/厂商 SDK: {module}"
            )
