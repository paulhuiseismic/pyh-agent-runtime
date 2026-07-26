"""T013-T014 [US2]: 查询排序与上限、空库、跨租户隔离。"""

import json

import httpx
import pytest

from kernel.memory import LongTermMemory
from kernel.provider import InvalidRequestError, LLMProvider, Message
from tests.unit.memory.conftest import MODEL


def make_memory(db_path, price_table, payload_by_marker=None) -> LongTermMemory:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        transcript = body["messages"][1]["content"]
        marker = transcript.split(": ", 1)[1]
        payload = (payload_by_marker or {}).get(marker, json.dumps([]))
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


async def test_query_ordered_by_recency_and_limited(db_path, price_table):
    payloads = {
        f"h{i}": json.dumps([{"category": f"cat{i}", "content": f"pref{i}"}]) for i in range(5)
    }
    memory = make_memory(db_path, price_table, payloads)

    for i in range(5):
        await memory.extract((Message(role="user", content=f"h{i}"),), tenant_id="tenant-a")

    stored = await memory.query(tenant_id="tenant-a", limit=3)
    assert len(stored) == 3
    # 最新写入的在前
    assert stored[0].content == "pref4"
    assert stored[1].content == "pref3"
    assert stored[2].content == "pref2"
    await memory.aclose()


async def test_query_empty_store_returns_empty_list(db_path, price_table):
    memory = make_memory(db_path, price_table)
    stored = await memory.query(tenant_id="tenant-a")
    assert stored == []
    await memory.aclose()


@pytest.mark.parametrize("limit", [0, -1, -100])
async def test_query_non_positive_limit_rejected(db_path, price_table, limit):
    memory = make_memory(db_path, price_table)
    with pytest.raises(InvalidRequestError):
        await memory.query(tenant_id="tenant-a", limit=limit)
    await memory.aclose()


async def test_cross_tenant_query_isolation(db_path, price_table):
    payload = json.dumps([{"category": "cat", "content": "shared-marker"}])
    memory = make_memory(db_path, price_table, {"h": payload})

    await memory.extract((Message(role="user", content="h"),), tenant_id="tenant-a")

    stored_a = await memory.query(tenant_id="tenant-a")
    stored_b = await memory.query(tenant_id="tenant-b")
    assert len(stored_a) == 1
    assert stored_b == []
    await memory.aclose()
