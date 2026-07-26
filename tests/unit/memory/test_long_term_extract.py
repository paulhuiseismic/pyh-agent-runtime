"""T008-T010 [US1]: 提炼写入、失败容错、并发提炼。"""

import asyncio
import json

import httpx
import pytest

from kernel.memory import LongTermMemory
from kernel.provider import Message
from tests.unit.memory.conftest import MODEL, erroring_provider


def make_extraction_transport(payload: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": MODEL,
                "choices": [{"message": {"role": "assistant", "content": payload}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
            },
        )

    return httpx.MockTransport(handler)


def make_memory(db_path, price_table, payload: str) -> LongTermMemory:
    from kernel.provider import LLMProvider

    provider = LLMProvider(
        base_url="http://stub", price_table=price_table, transport=make_extraction_transport(payload)
    )
    return LongTermMemory(db_path=db_path, provider=provider, model=MODEL)


async def test_extraction_with_preference_is_written(db_path, price_table):
    payload = json.dumps([{"category": "response_style", "content": "喜欢简洁的回答"}])
    memory = make_memory(db_path, price_table, payload)
    history = (Message(role="user", content="我更喜欢简洁的回答，不要长篇大论"),)

    result = await memory.extract(history, tenant_id="tenant-a")
    assert len(result.entries) == 1

    stored = await memory.query(tenant_id="tenant-a")
    assert stored[0].content == "喜欢简洁的回答"
    assert stored[0].category == "response_style"
    await memory.aclose()


async def test_extraction_with_nothing_worth_remembering_writes_nothing(db_path, price_table):
    memory = make_memory(db_path, price_table, "[]")
    history = (Message(role="user", content="今天天气怎么样"),)

    result = await memory.extract(history, tenant_id="tenant-a")
    assert result.entries == []

    stored = await memory.query(tenant_id="tenant-a")
    assert stored == []
    await memory.aclose()


async def test_empty_history_does_not_call_provider(db_path, price_table):
    call_count = []

    def handler(request: httpx.Request) -> httpx.Response:
        call_count.append(1)
        return httpx.Response(200, json={"model": MODEL, "choices": [], "usage": {}})

    from kernel.provider import LLMProvider

    provider = LLMProvider(
        base_url="http://stub", price_table=price_table, transport=httpx.MockTransport(handler)
    )
    memory = LongTermMemory(db_path=db_path, provider=provider, model=MODEL)

    result = await memory.extract((), tenant_id="tenant-a")
    assert result.entries == []
    assert call_count == []  # 未发起任何 provider 调用
    await memory.aclose()


async def test_provider_failure_leaves_store_unchanged(db_path, price_table):
    provider = erroring_provider(httpx.ConnectError("boom"))
    memory = LongTermMemory(db_path=db_path, provider=provider, model=MODEL)
    history = (Message(role="user", content="我喜欢简洁的回答"),)

    with pytest.raises(Exception):
        await memory.extract(history, tenant_id="tenant-a")

    stored = await memory.query(tenant_id="tenant-a")
    assert stored == []  # 库中无任何写入
    await memory.aclose()


async def test_concurrent_extractions_do_not_lose_entries(db_path, price_table):
    from kernel.provider import LLMProvider

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        transcript = body["messages"][1]["content"]  # "user: cat{i}" 格式（extraction.py 拼接）
        marker = transcript.split(": ", 1)[1]
        payload = json.dumps([{"category": marker, "content": f"pref-{marker}"}])
        return httpx.Response(
            200,
            json={
                "model": MODEL,
                "choices": [{"message": {"role": "assistant", "content": payload}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
            },
        )

    provider = LLMProvider(base_url="http://stub", price_table=price_table, transport=httpx.MockTransport(handler))
    memory = LongTermMemory(db_path=db_path, provider=provider, model=MODEL)

    histories = [(Message(role="user", content=f"cat{i}"),) for i in range(5)]
    await asyncio.gather(*(memory.extract(h, tenant_id="tenant-a") for h in histories))

    stored = await memory.query(tenant_id="tenant-a", limit=10)
    assert len(stored) == 5  # 各不同类别的条目全部写入，互不丢失
    assert {e.category for e in stored} == {f"cat{i}" for i in range(5)}
    await memory.aclose()
