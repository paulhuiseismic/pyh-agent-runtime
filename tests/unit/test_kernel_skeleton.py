"""T023 [US4] + 002 更新: 四模块可实例化、Protocol 结构检查、零平台层依赖（SC-005）。

react 模块自 002 起由 ReactEngine 完整实现（SingleShotReactLoop 占位已移除，
FR-011），本文件的 react 相关断言随之改为对 ReactEngine 的最小烟雾测试；
memory/tool 仍为 001 交付的占位实现，断言不变。
"""

import ast
import json
from pathlib import Path

import httpx
import pytest

from kernel.memory import Memory, NoopMemory
from kernel.provider import (
    InvalidRequestError,
    LLMProvider,
    Message,
    ModelPrice,
    PriceTable,
)
from kernel.react import ReactEngine, ReactLoop
from kernel.tool import EchoTool, Tool

KERNEL_SRC = Path(__file__).resolve().parents[2] / "src" / "kernel"

# 内核只允许 import 标准库、kernel 自身与这些第三方库（plan.md 技术上下文）
ALLOWED_THIRD_PARTY = {"httpx", "opentelemetry"}
# 平台层/厂商 SDK 的禁止清单（零依赖断言的显式黑名单示例）
FORBIDDEN_PREFIXES = ("platform_", "openai", "anthropic", "litellm", "langfuse")

_MODEL = "skeleton-test-model"


def _final_answer_provider(content: str = "done") -> LLMProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.dumps({"action": "final_answer", "content": content})
        return httpx.Response(
            200,
            json={
                "model": _MODEL,
                "choices": [{"message": {"role": "assistant", "content": payload}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    return LLMProvider(
        base_url="http://stub",
        price_table=PriceTable(prices={_MODEL: ModelPrice(0.01, 0.03)}),
        transport=httpx.MockTransport(handler),
    )


class TestInstantiation:
    def test_all_placeholder_implementations_instantiate(self):
        assert isinstance(NoopMemory(), Memory)
        engine = ReactEngine(provider=_final_answer_provider(), tools={}, model=_MODEL)
        assert isinstance(engine, ReactLoop)
        assert isinstance(EchoTool(), Tool)

    async def test_react_engine_runs(self):
        engine = ReactEngine(provider=_final_answer_provider("hello"), tools={}, model=_MODEL)
        result = await engine.run("test goal", tenant_id="tenant-a", max_steps=5)
        assert result == "hello"

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
        engine = ReactEngine(provider=_final_answer_provider(), tools={}, model=_MODEL)
        with pytest.raises(InvalidRequestError):
            await engine.run("goal", tenant_id="tenant-a", max_steps=max_steps)

    async def test_missing_tenant_rejected(self):
        engine = ReactEngine(provider=_final_answer_provider(), tools={}, model=_MODEL)
        with pytest.raises(InvalidRequestError):
            await engine.run("goal", tenant_id=" ", max_steps=5)


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
