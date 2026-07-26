"""T025: 输出截断、span 属性、遥测容错。"""

import json

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from kernel.tool import SandboxedTool, SandboxLimits, SandboxToolExecutionError


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


async def test_output_truncated_beyond_limit(echo_args_command):
    long_value = "x" * 5000
    limits = SandboxLimits(max_output_bytes=100)
    tool = SandboxedTool(
        name="echo", description="echo", command=echo_args_command, limits=limits
    )
    result = await tool.invoke({"data": long_value}, tenant_id="tenant-a")
    assert len(result) < 5000
    assert "输出已截断" in result


async def test_success_span_attributes(echo_args_command, span_exporter):
    tool = SandboxedTool(name="echo", description="echo", command=echo_args_command)
    await tool.invoke({"a": 1}, tenant_id="tenant-a")

    spans = [s for s in span_exporter.get_finished_spans() if s.name == "tool.invoke"]
    assert len(spans) == 1
    assert spans[0].attributes["tenant_id"] == "tenant-a"
    assert spans[0].attributes["tool_name"] == "echo"
    assert spans[0].attributes["result_type"] == "success"
    assert spans[0].attributes["duration_seconds"] >= 0


async def test_failure_span_result_type(exit_nonzero_command, span_exporter):
    tool = SandboxedTool(name="fail", description="fails", command=exit_nonzero_command)
    with pytest.raises(SandboxToolExecutionError):
        await tool.invoke({}, tenant_id="tenant-a")

    spans = [s for s in span_exporter.get_finished_spans() if s.name == "tool.invoke"]
    assert spans[0].attributes["result_type"] == "nonzero_exit"


async def test_telemetry_failure_does_not_affect_invoke(
    echo_args_command, span_exporter, monkeypatch
):
    from kernel.tool import telemetry as tool_telemetry

    class BrokenTracer:
        def start_as_current_span(self, *args, **kwargs):
            raise RuntimeError("telemetry backend down")

    monkeypatch.setattr(tool_telemetry, "_tracer", BrokenTracer())
    tool = SandboxedTool(name="echo", description="echo", command=echo_args_command)
    result = await tool.invoke({"a": 1}, tenant_id="tenant-a")
    assert json.loads(result) == {"a": 1}
