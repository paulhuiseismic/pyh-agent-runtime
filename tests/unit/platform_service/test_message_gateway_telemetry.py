import dataclasses

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
from platform_service.message_gateway import build_message_gateway
from platform_service.models import InboundMessage
from tests.unit.platform_service.conftest import recording_callback_client, stub_provider


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


async def test_successful_message_produces_consistent_tenant_span_hierarchy(
    platform_config, channel_config, span_exporter
):
    callback_client, received = recording_callback_client()
    provider = stub_provider("42")
    session_memory = SqliteMemory(db_path=":memory:", provider=provider, model=platform_config.model)
    long_term_memory = LongTermMemory(
        db_path=":memory:", provider=provider, model=platform_config.model
    )
    try:
        agent_service = AgentService(
            provider=provider,
            tool_registry=ToolRegistry(),
            session_memory=session_memory,
            long_term_memory=long_term_memory,
            config=platform_config,
        )
        config_with_channel = dataclasses.replace(platform_config, channels=[channel_config])
        gateway = await build_message_gateway(
            config_with_channel, agent_service=agent_service, callback_client=callback_client
        )

        await gateway.handle_inbound(
            InboundMessage(
                channel_id="demo-channel",
                external_message_id="msg-1",
                sender="user-1",
                text="1+1=?",
            )
        )
        await gateway.wait_for_background_tasks()

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
    finally:
        await session_memory.aclose()
        await long_term_memory.aclose()
        await callback_client.aclose()


async def test_unknown_channel_produces_no_spans(platform_config, channel_config, span_exporter):
    from platform_service.errors import ChannelNotFoundError

    callback_client, received = recording_callback_client()
    provider = stub_provider("42")
    session_memory = SqliteMemory(db_path=":memory:", provider=provider, model=platform_config.model)
    long_term_memory = LongTermMemory(
        db_path=":memory:", provider=provider, model=platform_config.model
    )
    try:
        agent_service = AgentService(
            provider=provider,
            tool_registry=ToolRegistry(),
            session_memory=session_memory,
            long_term_memory=long_term_memory,
            config=platform_config,
        )
        config_with_channel = dataclasses.replace(platform_config, channels=[channel_config])
        gateway = await build_message_gateway(
            config_with_channel, agent_service=agent_service, callback_client=callback_client
        )

        with pytest.raises(ChannelNotFoundError):
            await gateway.handle_inbound(
                InboundMessage(
                    channel_id="unknown-channel",
                    external_message_id="msg-1",
                    sender="user-1",
                    text="1+1=?",
                )
            )
        await gateway.wait_for_background_tasks()

        assert span_exporter.get_finished_spans() == ()
    finally:
        await session_memory.aclose()
        await long_term_memory.aclose()
        await callback_client.aclose()
