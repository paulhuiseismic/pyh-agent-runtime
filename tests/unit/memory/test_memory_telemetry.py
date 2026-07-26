"""T019 [US3]: 操作 span 属性、压缩标注、父子 span、遥测容错。"""

import httpx
import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from kernel.memory import ContextBudget, SqliteMemory
from kernel.provider import Message
from tests.unit.memory.conftest import MODEL, erroring_provider, scripted_summary_provider


@pytest.fixture
def span_exporter():
    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    yield exporter
    exporter.clear()


def msg(i: int) -> Message:
    return Message(role="user", content=f"msg{i}")


async def test_operation_span_without_compaction(db_path, price_table, span_exporter):
    provider = scripted_summary_provider(price_table, [])
    memory = SqliteMemory(db_path=db_path, provider=provider, model=MODEL)

    await memory.append("s1", msg(0), tenant_id="tenant-a")

    spans = [s for s in span_exporter.get_finished_spans() if s.name == "memory.append"]
    assert len(spans) == 1
    assert spans[0].attributes["tenant_id"] == "tenant-a"
    assert spans[0].attributes["session_id"] == "s1"
    assert spans[0].attributes["memory.compaction_triggered"] is False
    await memory.aclose()


async def test_compaction_triggered_span_and_parent_child(db_path, price_table, span_exporter):
    budget = ContextBudget(max_context_tokens=3, keep_recent_messages=1)
    provider = scripted_summary_provider(price_table, ["summ"])
    memory = SqliteMemory(db_path=db_path, provider=provider, model=MODEL, budget=budget)

    for i in range(4):
        await memory.append("s1", msg(i), tenant_id="tenant-a")

    spans = span_exporter.get_finished_spans()
    append_spans = [s for s in spans if s.name == "memory.append"]
    chat_spans = [s for s in spans if s.name.startswith("chat ")]

    assert len(chat_spans) == 1  # 仅第 4 次 append 触发了一次压缩调用
    triggering_span = next(
        s for s in append_spans if s.attributes["memory.compaction_triggered"] is True
    )
    assert chat_spans[0].parent.span_id == triggering_span.context.span_id
    await memory.aclose()


async def test_telemetry_failure_does_not_affect_operation(
    db_path, price_table, span_exporter, monkeypatch
):
    from kernel.memory import telemetry as memory_telemetry

    class BrokenTracer:
        def start_as_current_span(self, *args, **kwargs):
            raise RuntimeError("telemetry backend down")

    monkeypatch.setattr(memory_telemetry, "_tracer", BrokenTracer())
    provider = scripted_summary_provider(price_table, [])
    memory = SqliteMemory(db_path=db_path, provider=provider, model=MODEL)

    await memory.append("s1", msg(0), tenant_id="tenant-a")
    history = await memory.load("s1", tenant_id="tenant-a")
    assert [m.content for m in history] == ["msg0"]
    await memory.aclose()
