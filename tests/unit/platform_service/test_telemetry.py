import tempfile
from pathlib import Path

import httpx
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
from platform_service.agent_service import AgentService
from platform_service.app import create_app
from tests.unit.platform_service.conftest import stub_provider


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


@pytest.fixture
def db_paths():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield (
            str(Path(tmpdir) / "session.db"),
            str(Path(tmpdir) / "long_term.db"),
        )


async def _build_app(platform_config, db_paths, provider=None):
    provider = provider or stub_provider("hello world")
    session_memory = SqliteMemory(
        db_path=db_paths[0], provider=provider, model=platform_config.model
    )
    long_term_memory = LongTermMemory(
        db_path=db_paths[1], provider=provider, model=platform_config.model
    )
    service = AgentService(
        provider=provider,
        tool_registry=ToolRegistry(),
        session_memory=session_memory,
        long_term_memory=long_term_memory,
        config=platform_config,
    )
    try:
        yield create_app(platform_config, agent_service=service)
    finally:
        await session_memory.aclose()
        await long_term_memory.aclose()


async def test_platform_request_span_is_parent_of_kernel_chat_span(
    platform_config, db_paths, span_exporter
):
    async for app in _build_app(platform_config, db_paths):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v1/agent/run",
                headers={"X-API-Key": "key-a"},
                json={"goal": "1+1?"},
            )
        assert response.status_code == 200

        spans = span_exporter.get_finished_spans()
        root_spans = [s for s in spans if s.name == "platform.request"]
        assert len(root_spans) == 1
        root = root_spans[0]
        assert root.attributes["tenant_id"] == "tenant-a"
        assert root.attributes["result"] == "success"

        # 层级为 platform.request -> react.step -> chat {model}；同一整条链路
        # 必须落在同一个 trace 内，且每一层都携带一致的 tenant_id（SC-005）。
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


async def test_unauthenticated_request_produces_no_kernel_spans(
    platform_config, db_paths, span_exporter
):
    async for app in _build_app(platform_config, db_paths):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v1/agent/run",
                headers={"X-API-Key": "not-a-real-key"},
                json={"goal": "1+1?"},
            )
        assert response.status_code == 401

        spans = span_exporter.get_finished_spans()
        assert spans == ()
