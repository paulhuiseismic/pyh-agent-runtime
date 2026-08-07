import asyncio
import dataclasses
import time

import httpx

from kernel.memory import SqliteMemory
from kernel.memory.long_term import LongTermMemory
from kernel.tool import ToolRegistry
from platform_service.agent_service import AgentService
from platform_service.app import create_app
from platform_service.message_gateway import build_message_gateway
from tests.unit.platform_service.conftest import (
    recording_callback_client,
    slow_stub_provider,
    stub_provider,
)


async def _build_app(platform_config, channel_config, provider, callback_client):
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
    app = create_app(config_with_channel, agent_service=agent_service, message_gateway=gateway)
    return app, gateway, session_memory, long_term_memory


def _payload(**overrides) -> dict:
    payload = {
        "channel_id": "demo-channel",
        "external_message_id": "msg-1",
        "sender": "user-1",
        "text": "1+1=?",
    }
    payload.update(overrides)
    return payload


async def test_inbound_message_accepted(platform_config, channel_config):
    callback_client, received = recording_callback_client()
    app, gateway, session_memory, long_term_memory = await _build_app(
        platform_config, channel_config, stub_provider("42"), callback_client
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/v1/messages/inbound", json=_payload())
        assert response.status_code == 202
        assert response.json() == {"accepted": True, "duplicate": False}

        await gateway.wait_for_background_tasks()
        assert len(received) == 1
        assert received[0]["status"] == "success"
    finally:
        await session_memory.aclose()
        await long_term_memory.aclose()
        await callback_client.aclose()


async def test_inbound_message_response_latency_independent_of_processing(
    platform_config, channel_config
):
    callback_client, received = recording_callback_client()
    app, gateway, session_memory, long_term_memory = await _build_app(
        platform_config, channel_config, slow_stub_provider(1.0), callback_client
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            start = time.monotonic()
            response = await client.post("/v1/messages/inbound", json=_payload())
            elapsed = time.monotonic() - start
        assert response.status_code == 202
        assert elapsed < 0.5  # provider 延迟 1.0s，远大于此阈值（SC-001）

        await gateway.wait_for_background_tasks()
        assert len(received) == 1
        assert received[0]["status"] == "success"
    finally:
        await session_memory.aclose()
        await long_term_memory.aclose()
        await callback_client.aclose()


async def test_unknown_channel_returns_404(platform_config, channel_config):
    callback_client, received = recording_callback_client()
    app, gateway, session_memory, long_term_memory = await _build_app(
        platform_config, channel_config, stub_provider("42"), callback_client
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v1/messages/inbound", json=_payload(channel_id="unknown-channel")
            )
        assert response.status_code == 404

        await gateway.wait_for_background_tasks()
        assert received == []
    finally:
        await session_memory.aclose()
        await long_term_memory.aclose()
        await callback_client.aclose()


async def test_missing_text_returns_422(platform_config, channel_config):
    callback_client, received = recording_callback_client()
    app, gateway, session_memory, long_term_memory = await _build_app(
        platform_config, channel_config, stub_provider("42"), callback_client
    )
    try:
        payload = _payload()
        del payload["text"]
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/v1/messages/inbound", json=payload)
        assert response.status_code == 422
    finally:
        await session_memory.aclose()
        await long_term_memory.aclose()
        await callback_client.aclose()


async def test_duplicate_delivery_only_triggers_one_callback(platform_config, channel_config):
    callback_client, received = recording_callback_client()
    app, gateway, session_memory, long_term_memory = await _build_app(
        platform_config, channel_config, stub_provider("42"), callback_client
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            first = await client.post("/v1/messages/inbound", json=_payload())
            await gateway.wait_for_background_tasks()
            second = await client.post("/v1/messages/inbound", json=_payload())
            await gateway.wait_for_background_tasks()

        assert first.json()["duplicate"] is False
        assert second.json()["duplicate"] is True
        assert len(received) == 1
    finally:
        await session_memory.aclose()
        await long_term_memory.aclose()
        await callback_client.aclose()
