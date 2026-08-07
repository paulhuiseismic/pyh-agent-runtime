import asyncio
import dataclasses

from kernel.memory import SqliteMemory
from kernel.memory.long_term import LongTermMemory
from kernel.tool import ToolRegistry
from platform_service.agent_service import AgentService
from platform_service.message_gateway import (
    MessageGateway,
    ProcessedMessageRegistry,
    build_message_gateway,
)
from platform_service.models import InboundMessage
from tests.unit.platform_service.conftest import (
    erroring_provider,
    failing_callback_client,
    recording_callback_client,
    slow_stub_provider,
    stub_provider,
)


async def test_check_and_mark_first_time_returns_true():
    registry = ProcessedMessageRegistry()
    assert await registry.check_and_mark("c1", "m1") is True


async def test_check_and_mark_duplicate_returns_false():
    registry = ProcessedMessageRegistry()
    await registry.check_and_mark("c1", "m1")
    assert await registry.check_and_mark("c1", "m1") is False


async def test_check_and_mark_different_keys_independent():
    registry = ProcessedMessageRegistry()
    assert await registry.check_and_mark("c1", "m1") is True
    assert await registry.check_and_mark("c1", "m2") is True
    assert await registry.check_and_mark("c2", "m1") is True


async def test_check_and_mark_concurrent_calls_only_one_succeeds():
    registry = ProcessedMessageRegistry()
    results = await asyncio.gather(
        *[registry.check_and_mark("c1", "m1") for _ in range(10)]
    )
    assert sum(1 for r in results if r) == 1


async def _build_gateway(platform_config, channel_config, provider, callback_client):
    session_memory = SqliteMemory(db_path=":memory:", provider=provider, model=platform_config.model)
    long_term_memory = LongTermMemory(
        db_path=":memory:", provider=provider, model=platform_config.model
    )
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
    return gateway, session_memory, long_term_memory


def _message(**overrides) -> InboundMessage:
    kwargs = dict(
        channel_id="demo-channel",
        external_message_id="msg-1",
        sender="user-1",
        text="1+1=?",
        conversation_id=None,
    )
    kwargs.update(overrides)
    return InboundMessage(**kwargs)


async def test_handle_inbound_success(platform_config, channel_config):
    callback_client, received = recording_callback_client()
    gateway, session_memory, long_term_memory = await _build_gateway(
        platform_config, channel_config, stub_provider("42"), callback_client
    )
    try:
        result = await gateway.handle_inbound(_message())
        assert result.accepted is True
        assert result.duplicate is False

        await gateway.wait_for_background_tasks()
        assert len(received) == 1
        assert received[0]["status"] == "success"
        assert received[0]["answer"] == "42"
        assert received[0]["external_message_id"] == "msg-1"
    finally:
        await session_memory.aclose()
        await long_term_memory.aclose()
        await callback_client.aclose()


async def test_handle_inbound_kernel_error(platform_config, channel_config):
    callback_client, received = recording_callback_client()
    gateway, session_memory, long_term_memory = await _build_gateway(
        platform_config, channel_config, erroring_provider(RuntimeError("boom")), callback_client
    )
    try:
        await gateway.handle_inbound(_message())
        await gateway.wait_for_background_tasks()
        assert len(received) == 1
        assert received[0]["status"] == "kernel_error"
        assert received[0]["answer"] is None
        assert received[0]["error"] is not None
    finally:
        await session_memory.aclose()
        await long_term_memory.aclose()
        await callback_client.aclose()


async def test_handle_inbound_timeout(platform_config, channel_config):
    fast_timeout_config = dataclasses.replace(platform_config, request_timeout_seconds=0.05)
    callback_client, received = recording_callback_client()
    gateway, session_memory, long_term_memory = await _build_gateway(
        fast_timeout_config, channel_config, slow_stub_provider(1.0), callback_client
    )
    try:
        await gateway.handle_inbound(_message())
        await gateway.wait_for_background_tasks()
        assert len(received) == 1
        assert received[0]["status"] == "timeout"
    finally:
        await session_memory.aclose()
        await long_term_memory.aclose()
        await callback_client.aclose()


async def test_send_callback_retries_exhausted_does_not_raise(
    platform_config, channel_config, caplog
):
    call_counter: list[int] = []
    callback_client = failing_callback_client(call_counter)
    gateway, session_memory, long_term_memory = await _build_gateway(
        platform_config, channel_config, stub_provider("42"), callback_client
    )
    try:
        await gateway.handle_inbound(_message())

        # wait_for_background_tasks() 内部用 asyncio.gather() 等待所有
        # 已调度任务；若 _process_and_callback() 内部有未被吞掉的异常，
        # gather 会把它重新抛出——本调用不抛异常即证明重试耗尽后未向上
        # 传播（FR-008）。
        with caplog.at_level("WARNING"):
            await gateway.wait_for_background_tasks()

        assert len(call_counter) == platform_config.callback_max_retries
        assert any("callback delivery failed" in r.message for r in caplog.records)
    finally:
        await session_memory.aclose()
        await long_term_memory.aclose()
        await callback_client.aclose()
