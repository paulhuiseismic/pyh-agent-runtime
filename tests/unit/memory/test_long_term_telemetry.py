"""T020: extract/query 操作 span 属性、父子 span、遥测容错。"""

import json

import httpx
import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from kernel.memory import LongTermMemory
from kernel.provider import LLMProvider, Message
from tests.unit.memory.conftest import MODEL


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


def make_memory(db_path, price_table, payload: str) -> LongTermMemory:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": MODEL,
                "choices": [{"message": {"role": "assistant", "content": payload}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
            },
        )

    provider = LLMProvider(base_url="http://stub", price_table=price_table, transport=httpx.MockTransport(handler))
    return LongTermMemory(db_path=db_path, provider=provider, model=MODEL)


async def test_extract_span_attributes_and_parent_child(db_path, price_table, span_exporter):
    payload = json.dumps([{"category": "food", "content": "喜欢辣的"}])
    memory = make_memory(db_path, price_table, payload)

    await memory.extract((Message(role="user", content="h"),), tenant_id="tenant-a")

    spans = span_exporter.get_finished_spans()
    extract_spans = [s for s in spans if s.name == "long_term_memory.extract"]
    chat_spans = [s for s in spans if s.name.startswith("chat ")]
    assert len(extract_spans) == 1
    assert extract_spans[0].attributes["tenant_id"] == "tenant-a"
    assert extract_spans[0].attributes["operation"] == "extract"
    assert len(chat_spans) == 1
    assert chat_spans[0].parent.span_id == extract_spans[0].context.span_id
    await memory.aclose()


async def test_query_span_attributes_no_child_span(db_path, price_table, span_exporter):
    memory = make_memory(db_path, price_table, "[]")

    await memory.query(tenant_id="tenant-a")

    spans = span_exporter.get_finished_spans()
    query_spans = [s for s in spans if s.name == "long_term_memory.query"]
    assert len(query_spans) == 1
    assert query_spans[0].attributes["tenant_id"] == "tenant-a"
    assert query_spans[0].attributes["operation"] == "query"
    assert not any(s.name.startswith("chat ") for s in spans)  # query 无子 span
    await memory.aclose()


async def test_telemetry_failure_does_not_affect_operation(
    db_path, price_table, span_exporter, monkeypatch
):
    from kernel.memory import telemetry as memory_telemetry

    class BrokenTracer:
        def start_as_current_span(self, *args, **kwargs):
            raise RuntimeError("telemetry backend down")

    monkeypatch.setattr(memory_telemetry, "_tracer", BrokenTracer())
    payload = json.dumps([{"category": "food", "content": "喜欢辣的"}])
    memory = make_memory(db_path, price_table, payload)

    result = await memory.extract((Message(role="user", content="h"),), tenant_id="tenant-a")
    assert len(result.entries) == 1
    stored = await memory.query(tenant_id="tenant-a")
    assert len(stored) == 1
    await memory.aclose()
