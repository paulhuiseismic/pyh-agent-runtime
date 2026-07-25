"""T010-T012 [US1]: 直接回答 / 工具调用后回答 / 未注册工具容错。"""

import json

from kernel.react import ReactEngine
from tests.unit.react.conftest import MODEL, StubTool, scripted_provider


def make_engine(price_table, responses, tools=None):
    provider = scripted_provider(price_table, responses)
    return ReactEngine(provider=provider, tools=tools or {}, model=MODEL)


async def test_direct_answer_without_tool_call(price_table):
    responses = [json.dumps({"action": "final_answer", "content": "42"})]
    engine = make_engine(price_table, responses)
    result = await engine.run("what is the answer", tenant_id="tenant-a", max_steps=5)
    assert result == "42"


async def test_tool_call_then_answer(price_table):
    tool = StubTool("search", result="搜索到结果 X")
    responses = [
        json.dumps({"action": "call_tool", "tool": "search", "arguments": {"q": "X"}}),
        json.dumps({"action": "final_answer", "content": "答案基于搜索到结果 X"}),
    ]
    engine = make_engine(price_table, responses, tools={"search": tool})
    result = await engine.run("find X", tenant_id="tenant-a", max_steps=5)
    assert result == "答案基于搜索到结果 X"
    assert tool.call_count == 1
    assert tool.last_arguments == {"q": "X"}


async def test_unregistered_tool_becomes_observation_and_continues(price_table):
    responses = [
        json.dumps({"action": "call_tool", "tool": "does-not-exist", "arguments": {}}),
        json.dumps({"action": "final_answer", "content": "fallback answer"}),
    ]
    engine = make_engine(price_table, responses, tools={})
    result = await engine.run("goal", tenant_id="tenant-a", max_steps=5)
    assert result == "fallback answer"  # 循环未崩溃，继续到第二步给出答案


async def test_tool_raises_exception_becomes_observation(price_table):
    tool = StubTool("broken", raises=RuntimeError("boom"))
    responses = [
        json.dumps({"action": "call_tool", "tool": "broken", "arguments": {}}),
        json.dumps({"action": "final_answer", "content": "recovered"}),
    ]
    engine = make_engine(price_table, responses, tools={"broken": tool})
    result = await engine.run("goal", tenant_id="tenant-a", max_steps=5)
    assert result == "recovered"
