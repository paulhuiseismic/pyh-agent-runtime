import json

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from kernel.memory import SqliteMemory
from kernel.memory.long_term import LongTermMemory
from kernel.tool import ToolRegistry
from platform_service import cli
from platform_service.agent_service import AgentService
from tests.unit.platform_service.conftest import stub_provider

MODEL = "platform-test-model"


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


def _write_config_file(path, platform_config) -> None:
    payload = {
        "tenants": [
            {
                "api_key": t.api_key,
                "tenant_id": t.tenant_id,
                "max_concurrent_requests": t.max_concurrent_requests,
            }
            for t in platform_config.tenants
        ],
        "global_max_concurrent_requests": platform_config.global_max_concurrent_requests,
        "request_timeout_seconds": platform_config.request_timeout_seconds,
        "model": platform_config.model,
        "max_steps": platform_config.max_steps,
        "provider_base_url": platform_config.provider_base_url,
        "price_table": {
            MODEL: {"input_per_1k_usd": 0.01, "output_per_1k_usd": 0.03},
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


async def test_successful_run_produces_consistent_tenant_span_hierarchy(
    platform_config, tmp_path, span_exporter
):
    config_path = tmp_path / "config.json"
    _write_config_file(config_path, platform_config)

    provider = stub_provider("42")
    session_memory = SqliteMemory(db_path=":memory:", provider=provider, model=platform_config.model)
    long_term_memory = LongTermMemory(
        db_path=":memory:", provider=provider, model=platform_config.model
    )
    try:
        service = AgentService(
            provider=provider,
            tool_registry=ToolRegistry(),
            session_memory=session_memory,
            long_term_memory=long_term_memory,
            config=platform_config,
        )
        exit_code, stdout, stderr = await cli.run(
            ["1+1=?"],
            {"PLATFORM_SERVICE_API_KEY": "key-a", "PLATFORM_SERVICE_CONFIG": str(config_path)},
            agent_service=service,
        )
    finally:
        await session_memory.aclose()
        await long_term_memory.aclose()

    assert exit_code == cli.EXIT_SUCCESS

    spans = span_exporter.get_finished_spans()
    root_spans = [s for s in spans if s.name == "platform.request"]
    assert len(root_spans) == 1
    root = root_spans[0]
    assert root.attributes["tenant_id"] == "tenant-a"
    assert root.attributes["result"] == "success"

    step_spans = [s for s in spans if s.name == "react.step"]
    assert len(step_spans) >= 1
    for step_span in step_spans:
        assert step_span.parent.span_id == root.context.span_id
        assert step_span.context.trace_id == root.context.trace_id

    chat_spans = [s for s in spans if s.name.startswith("chat ")]
    assert len(chat_spans) >= 1
    step_span_ids = {s.context.span_id for s in step_spans}
    for chat_span in chat_spans:
        assert chat_span.attributes["tenant_id"] == "tenant-a"
        assert chat_span.context.trace_id == root.context.trace_id
        assert chat_span.parent.span_id in step_span_ids


async def test_missing_api_key_produces_no_spans(platform_config, tmp_path, span_exporter):
    config_path = tmp_path / "config.json"
    _write_config_file(config_path, platform_config)

    exit_code, stdout, stderr = await cli.run(
        ["1+1=?"],
        {"PLATFORM_SERVICE_CONFIG": str(config_path)},
        agent_service=None,
    )
    assert exit_code == cli.EXIT_MISSING_API_KEY

    spans = span_exporter.get_finished_spans()
    assert spans == ()
