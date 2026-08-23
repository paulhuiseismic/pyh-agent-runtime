import asyncio
import dataclasses
import json

import httpx
import pytest

from kernel.memory import SqliteMemory
from kernel.memory.long_term import LongTermMemory
from kernel.provider import LLMProvider
from kernel.tool import ToolRegistry
from platform_service.agent_service import AgentService
from platform_service.errors import ChannelNotFoundError
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


async def _build_gateway(platform_config, channel_config, provider, callback_client, audit_store=None):
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
        audit_store=audit_store,
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


class _RefusingAgentService:
    """哨兵 AgentService：一旦被调用即断言失败，用于验证渠道未识别路径
    从未触及内核调用（US2 验收场景 1）。"""

    async def handle(self, request, *, tenant_id):
        raise AssertionError("AgentService.handle() 不应在渠道未识别路径下被调用")


async def test_handle_inbound_unknown_channel_raises_and_skips_processing(
    platform_config, channel_config
):
    callback_client, received = recording_callback_client()
    config_with_channel = dataclasses.replace(platform_config, channels=[channel_config])
    gateway = await build_message_gateway(
        config_with_channel,
        agent_service=_RefusingAgentService(),
        callback_client=callback_client,
    )
    try:
        with pytest.raises(ChannelNotFoundError):
            await gateway.handle_inbound(_message(channel_id="unknown-channel"))
        await gateway.wait_for_background_tasks()
        assert received == []
    finally:
        await callback_client.aclose()


async def test_handle_inbound_duplicate_delivery_only_processed_once(
    platform_config, channel_config
):
    callback_client, received = recording_callback_client()
    gateway, session_memory, long_term_memory = await _build_gateway(
        platform_config, channel_config, stub_provider("42"), callback_client
    )
    try:
        first = await gateway.handle_inbound(_message())
        await gateway.wait_for_background_tasks()
        second = await gateway.handle_inbound(_message())
        await gateway.wait_for_background_tasks()

        assert first.duplicate is False
        assert second.duplicate is True
        assert len(received) == 1
    finally:
        await session_memory.aclose()
        await long_term_memory.aclose()
        await callback_client.aclose()


async def test_conversation_continuity_across_messages(platform_config, channel_config):
    """两条消息共享同一 conversation_id 时，第二条的处理结果体现第一条
    积累的会话上下文（复用 003 会话记忆，US3 验收场景 1）。"""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        answer = "我记得你叫小明" if call_count > 1 else "好的"
        content = json.dumps({"action": "final_answer", "content": answer})
        return httpx.Response(
            200,
            json={
                "model": platform_config.model,
                "choices": [
                    {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
            },
        )

    provider = LLMProvider(
        base_url="http://stub",
        price_table=platform_config.price_table,
        transport=httpx.MockTransport(handler),
    )
    callback_client, received = recording_callback_client()
    gateway, session_memory, long_term_memory = await _build_gateway(
        platform_config, channel_config, provider, callback_client
    )
    try:
        await gateway.handle_inbound(
            _message(external_message_id="msg-1", conversation_id="conv-1", text="我叫小明")
        )
        await gateway.wait_for_background_tasks()

        await gateway.handle_inbound(
            _message(external_message_id="msg-2", conversation_id="conv-1", text="我叫什么名字？")
        )
        await gateway.wait_for_background_tasks()

        assert len(received) == 2
        assert received[1]["answer"] == "我记得你叫小明"
    finally:
        await session_memory.aclose()
        await long_term_memory.aclose()
        await callback_client.aclose()


async def test_handle_inbound_success_records_audit_entry_with_message_gateway_source(
    platform_config, channel_config, audit_store
):
    callback_client, received = recording_callback_client()
    gateway, session_memory, long_term_memory = await _build_gateway(
        platform_config, channel_config, stub_provider("42"), callback_client, audit_store=audit_store
    )
    try:
        await gateway.handle_inbound(_message())
        await gateway.wait_for_background_tasks()

        conn = await audit_store._get_conn()
        cursor = await conn.execute("SELECT tenant_id, source FROM audit_entries")
        rows = await cursor.fetchall()
        assert rows == [("tenant-a", "message_gateway")]
    finally:
        await session_memory.aclose()
        await long_term_memory.aclose()
        await callback_client.aclose()


async def test_handle_inbound_quota_exceeded_reports_via_callback(
    platform_config, channel_config, audit_store
):
    import dataclasses
    from datetime import datetime, timezone

    from platform_service.audit import AuditEntry

    quota_config = dataclasses.replace(
        platform_config,
        tenants=[
            dataclasses.replace(t, daily_cost_quota_usd=0.0001) if t.tenant_id == "tenant-a" else t
            for t in platform_config.tenants
        ],
    )
    await audit_store.record(
        AuditEntry(
            tenant_id="tenant-a",
            source="message_gateway",
            timestamp=datetime.now(timezone.utc),
            input_tokens=100,
            output_tokens=100,
            cost_usd=1.0,
            status="success",
        )
    )

    callback_client, received = recording_callback_client()
    gateway, session_memory, long_term_memory = await _build_gateway(
        quota_config, channel_config, stub_provider("42"), callback_client, audit_store=audit_store
    )
    try:
        await gateway.handle_inbound(_message())
        await gateway.wait_for_background_tasks()

        assert len(received) == 1
        assert received[0]["status"] == "quota_exceeded"
    finally:
        await session_memory.aclose()
        await long_term_memory.aclose()
        await callback_client.aclose()
