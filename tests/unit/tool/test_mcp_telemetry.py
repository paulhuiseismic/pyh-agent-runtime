import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from kernel.tool.mcp_client import McpServerConnection
from kernel.tool.mcp_tool import McpTool


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


async def test_connect_span_attributes(mcp_stdio_config, span_exporter):
    connection = McpServerConnection(mcp_stdio_config)
    await connection.connect(tenant_id="tenant-a")

    spans = [s for s in span_exporter.get_finished_spans() if s.name == "mcp.connect"]
    assert len(spans) == 1
    assert spans[0].attributes["tenant_id"] == "tenant-a"
    assert spans[0].attributes["transport"] == "stdio"
    assert spans[0].attributes["result"] == "success"
    await connection.disconnect(tenant_id="tenant-a")


async def test_disconnect_span_produced_once(mcp_stdio_config, span_exporter):
    connection = McpServerConnection(mcp_stdio_config)
    await connection.connect(tenant_id="tenant-a")
    await connection.disconnect(tenant_id="tenant-a")
    await connection.disconnect(tenant_id="tenant-a")  # no-op, must not re-emit

    spans = [
        s for s in span_exporter.get_finished_spans() if s.name == "mcp.disconnect"
    ]
    assert len(spans) == 1
    assert spans[0].attributes["tenant_id"] == "tenant-a"
    assert spans[0].attributes["transport"] == "stdio"


async def test_tool_invoke_span_result_type(mcp_stdio_config, span_exporter):
    connection = McpServerConnection(mcp_stdio_config)
    await connection.connect(tenant_id="tenant-a")
    tool = McpTool(name="echo", description="echo tool", connection=connection)
    await tool.invoke({"payload": {"a": 1}}, tenant_id="tenant-a")

    spans = [s for s in span_exporter.get_finished_spans() if s.name == "tool.invoke"]
    assert len(spans) == 1
    assert spans[0].attributes["tenant_id"] == "tenant-a"
    assert spans[0].attributes["tool_name"] == "echo"
    assert spans[0].attributes["result_type"] == "success"
    assert spans[0].attributes["duration_seconds"] >= 0
    await connection.disconnect(tenant_id="tenant-a")


async def test_telemetry_failure_does_not_affect_connect(mcp_stdio_config, monkeypatch):
    from kernel.tool import telemetry as tool_telemetry

    class BrokenTracer:
        def start_as_current_span(self, *args, **kwargs):
            raise RuntimeError("telemetry backend down")

    monkeypatch.setattr(tool_telemetry, "_tracer", BrokenTracer())
    connection = McpServerConnection(mcp_stdio_config)
    await connection.connect(tenant_id="tenant-a")
    tools = await connection.discover_tools()
    assert {t.name for t in tools} == {"echo", "slow", "fail"}
    await connection.disconnect(tenant_id="tenant-a")
