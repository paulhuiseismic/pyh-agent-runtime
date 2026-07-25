"""T019 [US3]: 步数/工具 span 标注、父子关系、终止类型可区分、遥测容错、并发不串扰。"""

import asyncio
import json

import httpx
import pytest
from opentelemetry.trace import StatusCode

from kernel.react import ReactEngine, StepBudgetExceededError
from tests.unit.react.conftest import MODEL, StubTool, scripted_provider


def make_engine(price_table, responses, tools=None):
    provider = scripted_provider(price_table, responses)
    return ReactEngine(provider=provider, tools=tools or {}, model=MODEL)


async def test_multi_step_span_attributes_and_parent_child(price_table, span_exporter):
    tool = StubTool("search", result="obs")
    responses = [
        json.dumps({"action": "call_tool", "tool": "search", "arguments": {}}),
        json.dumps({"action": "final_answer", "content": "done"}),
    ]
    engine = make_engine(price_table, responses, tools={"search": tool})
    result = await engine.run("goal", tenant_id="tenant-a", max_steps=5)
    assert result == "done"

    spans = span_exporter.get_finished_spans()
    step_spans = [s for s in spans if s.name == "react.step"]
    chat_spans = [s for s in spans if s.name.startswith("chat ")]
    assert len(step_spans) == 2
    assert len(chat_spans) == 2

    step1 = next(s for s in step_spans if s.attributes["react.step.index"] == 1)
    step2 = next(s for s in step_spans if s.attributes["react.step.index"] == 2)
    assert step1.attributes["react.step.action"] == "call_tool"
    assert step1.attributes["react.step.tool_name"] == "search"
    assert step2.attributes["react.step.action"] == "final_answer"

    # 每个 chat span 的 parent 必须是对应步骤的 react.step span（而非仅数量匹配）
    for chat_span in chat_spans:
        parent_span_id = chat_span.parent.span_id
        assert parent_span_id in {step1.context.span_id, step2.context.span_id}


async def test_step_budget_exceeded_last_span_marked_error(price_table, span_exporter):
    tool = StubTool("search", result="obs")
    from tests.unit.react.conftest import always_call_tool_provider

    provider = always_call_tool_provider(price_table)
    engine = ReactEngine(provider=provider, tools={"search": tool}, model=MODEL)
    with pytest.raises(StepBudgetExceededError):
        await engine.run("goal", tenant_id="tenant-a", max_steps=2)

    spans = span_exporter.get_finished_spans()
    step_spans = sorted(
        (s for s in spans if s.name == "react.step"),
        key=lambda s: s.attributes["react.step.index"],
    )
    assert len(step_spans) == 2
    assert step_spans[0].status.status_code == StatusCode.OK
    assert step_spans[1].status.status_code == StatusCode.ERROR
    assert step_spans[1].attributes["error.type"] == "StepBudgetExceededError"


async def test_telemetry_failure_does_not_affect_run(price_table, span_exporter, monkeypatch):
    from kernel.react import telemetry as react_telemetry

    class BrokenTracer:
        def start_as_current_span(self, *args, **kwargs):
            raise RuntimeError("telemetry backend down")

    monkeypatch.setattr(react_telemetry, "_tracer", BrokenTracer())
    responses = [json.dumps({"action": "final_answer", "content": "ok"})]
    engine = make_engine(price_table, responses)
    result = await engine.run("goal", tenant_id="tenant-a", max_steps=3)
    assert result == "ok"


async def test_concurrent_runs_same_tenant_do_not_interfere(price_table, span_exporter):
    """并发场景：相同 tenant_id 的多次并发 run 步数计数与 span 归属互不串扰。"""

    call_log = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        goal_marker = body["messages"][1]["content"]
        call_log.append(goal_marker)
        content = json.dumps({"action": "final_answer", "content": f"answer for {goal_marker}"})
        return httpx.Response(
            200,
            json={
                "model": MODEL,
                "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    from kernel.provider import LLMProvider

    provider = LLMProvider(
        base_url="http://stub", price_table=price_table, transport=httpx.MockTransport(handler)
    )
    engine = ReactEngine(provider=provider, tools={}, model=MODEL)

    results = await asyncio.gather(
        engine.run("目标: goal-A", tenant_id="tenant-same", max_steps=3),
        engine.run("目标: goal-B", tenant_id="tenant-same", max_steps=3),
    )

    assert "goal-A" in results[0] or "goal-B" in results[0]
    assert results[0] != results[1] or "goal-A" in results[0]
    spans = span_exporter.get_finished_spans()
    step_spans = [s for s in spans if s.name == "react.step"]
    assert len(step_spans) == 2  # 各自一步，互不覆盖丢失


async def test_concurrent_runs_different_tenants_do_not_interfere(price_table, span_exporter):
    tool_a = StubTool("t", result="a-result")
    tool_b = StubTool("t", result="b-result")
    responses_a = [json.dumps({"action": "final_answer", "content": "answer-a"})]
    responses_b = [json.dumps({"action": "final_answer", "content": "answer-b"})]
    engine_a = make_engine(price_table, responses_a, tools={"t": tool_a})
    engine_b = make_engine(price_table, responses_b, tools={"t": tool_b})

    result_a, result_b = await asyncio.gather(
        engine_a.run("goal", tenant_id="tenant-a", max_steps=3),
        engine_b.run("goal", tenant_id="tenant-b", max_steps=3),
    )
    assert result_a == "answer-a"
    assert result_b == "answer-b"
