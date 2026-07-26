"""T015-T017 [US3]: 同类别覆盖、不同类别独立、反复提炼不无限增长。

生产逻辑已在 T005 的 upsert_entries（SQLite UNIQUE(tenant_id, category) +
ON CONFLICT DO UPDATE）实现，本文件仅验证行为（research.md R3）。
"""

import json

import httpx

from kernel.memory import LongTermMemory
from kernel.provider import LLMProvider, Message
from tests.unit.memory.conftest import MODEL


def make_memory(db_path, price_table, payload_by_marker) -> LongTermMemory:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        transcript = body["messages"][1]["content"]
        marker = transcript.split(": ", 1)[1]
        payload = payload_by_marker.get(marker, json.dumps([]))
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


async def test_same_category_overwrites_previous_entry(db_path, price_table):
    payloads = {
        "h1": json.dumps([{"category": "response_style", "content": "喜欢简洁"}]),
        "h2": json.dumps([{"category": "response_style", "content": "喜欢详细"}]),
    }
    memory = make_memory(db_path, price_table, payloads)

    await memory.extract((Message(role="user", content="h1"),), tenant_id="tenant-a")
    await memory.extract((Message(role="user", content="h2"),), tenant_id="tenant-a")

    stored = await memory.query(tenant_id="tenant-a", limit=10)
    same_category = [e for e in stored if e.category == "response_style"]
    assert len(same_category) == 1
    assert same_category[0].content == "喜欢详细"
    await memory.aclose()


async def test_different_categories_coexist_independently(db_path, price_table):
    payloads = {
        "h1": json.dumps([{"category": "food", "content": "喜欢辣的"}]),
        "h2": json.dumps([{"category": "response_style", "content": "喜欢简洁"}]),
    }
    memory = make_memory(db_path, price_table, payloads)

    await memory.extract((Message(role="user", content="h1"),), tenant_id="tenant-a")
    await memory.extract((Message(role="user", content="h2"),), tenant_id="tenant-a")

    stored = await memory.query(tenant_id="tenant-a", limit=10)
    assert {e.category for e in stored} == {"food", "response_style"}
    assert len(stored) == 2
    await memory.aclose()


async def test_uncategorized_entries_each_added_independently(db_path, price_table):
    payloads = {
        f"h{i}": json.dumps([{"category": None, "content": f"random-fact-{i}"}]) for i in range(3)
    }
    memory = make_memory(db_path, price_table, payloads)

    for i in range(3):
        await memory.extract((Message(role="user", content=f"h{i}"),), tenant_id="tenant-a")

    stored = await memory.query(tenant_id="tenant-a", limit=10)
    assert len(stored) == 3  # 均为 category=None，互不冲突覆盖
    assert all(e.category is None for e in stored)
    await memory.aclose()


async def test_repeated_extraction_same_category_does_not_grow_unbounded(db_path, price_table):
    payloads = {f"h{i}": json.dumps([{"category": "mood", "content": f"mood-{i}"}]) for i in range(5)}
    memory = make_memory(db_path, price_table, payloads)

    for i in range(5):
        await memory.extract((Message(role="user", content=f"h{i}"),), tenant_id="tenant-a")

    stored = await memory.query(tenant_id="tenant-a", limit=100)
    mood_entries = [e for e in stored if e.category == "mood"]
    assert len(mood_entries) == 1
    assert mood_entries[0].content == "mood-4"  # 最后一次提炼的内容生效
    await memory.aclose()
