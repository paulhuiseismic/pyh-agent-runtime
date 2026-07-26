"""T009-T011 [US1]: 持久化读写、跨租户隔离、并发 append。"""

import asyncio

from kernel.memory import SqliteMemory
from kernel.provider import Message
from tests.unit.memory.conftest import MODEL, scripted_summary_provider


def make_memory(db_path, price_table, tools=None):
    provider = scripted_summary_provider(price_table, [])
    return SqliteMemory(db_path=db_path, provider=provider, model=MODEL)


async def test_append_and_load_preserves_order(db_path, price_table):
    memory = make_memory(db_path, price_table)
    await memory.append("s1", Message(role="user", content="one"), tenant_id="tenant-a")
    await memory.append("s1", Message(role="assistant", content="two"), tenant_id="tenant-a")
    await memory.append("s1", Message(role="user", content="three"), tenant_id="tenant-a")

    history = await memory.load("s1", tenant_id="tenant-a")
    assert [m.content for m in history] == ["one", "two", "three"]
    await memory.aclose()


async def test_data_persists_after_reopening_connection(db_path, price_table):
    memory1 = make_memory(db_path, price_table)
    await memory1.append("s1", Message(role="user", content="persisted"), tenant_id="tenant-a")
    await memory1.aclose()

    memory2 = make_memory(db_path, price_table)
    history = await memory2.load("s1", tenant_id="tenant-a")
    assert [m.content for m in history] == ["persisted"]
    await memory2.aclose()


async def test_nonexistent_session_returns_empty_list(db_path, price_table):
    memory = make_memory(db_path, price_table)
    history = await memory.load("does-not-exist", tenant_id="tenant-a")
    assert history == []
    await memory.aclose()


async def test_cross_tenant_isolation(db_path, price_table):
    memory = make_memory(db_path, price_table)
    await memory.append("shared-session", Message(role="user", content="from A"), tenant_id="tenant-a")
    await memory.append("shared-session", Message(role="user", content="from B"), tenant_id="tenant-b")

    history_a = await memory.load("shared-session", tenant_id="tenant-a")
    history_b = await memory.load("shared-session", tenant_id="tenant-b")

    assert [m.content for m in history_a] == ["from A"]
    assert [m.content for m in history_b] == ["from B"]
    await memory.aclose()


async def test_concurrent_append_does_not_lose_messages(db_path, price_table):
    memory = make_memory(db_path, price_table)
    messages = [Message(role="user", content=f"msg-{i}") for i in range(10)]

    await asyncio.gather(
        *(memory.append("s1", m, tenant_id="tenant-a") for m in messages)
    )

    history = await memory.load("s1", tenant_id="tenant-a")
    assert len(history) == 10  # 全部写入，无丢失
    assert {m.content for m in history} == {m.content for m in messages}  # 无重复
    await memory.aclose()
