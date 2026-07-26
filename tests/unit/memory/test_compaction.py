"""T014-T016 [US2]: 自动压缩触发、未超预算/边界、压缩失败容错。

消息内容故意设计为精确 4 字符（1 token，字符数/4 粗估策略下无余数），
使压缩触发的时机可精确计算，避免中文字符估算偏差带来的不确定性。
"""

import httpx
import pytest

from kernel.memory import ContextBudget, SqliteMemory
from kernel.memory.compaction import estimate_total_tokens
from kernel.memory.storage import SqliteStore
from kernel.provider import Message
from tests.unit.memory.conftest import MODEL, erroring_provider, scripted_summary_provider


def make_memory(db_path, price_table, budget, summaries=None):
    provider = scripted_summary_provider(price_table, summaries or [])
    return SqliteMemory(db_path=db_path, provider=provider, model=MODEL, budget=budget)


def msg(i: int) -> Message:
    return Message(role="user", content=f"msg{i}")  # 恰好 4 字符 = 1 token


async def test_compaction_triggers_and_falls_back_under_budget(db_path, price_table):
    # max_context_tokens=3：msg0+msg1+msg2 = 3 tokens（不超）；append msg3 时
    # 总量变为 4 tokens > 3，触发压缩，keep_recent_messages=1 只保留 msg3
    # 摘要文本刻意设为 4 字符（1 token），使压缩后总量（摘要 1 + 保留消息 1 = 2）
    # 回落到预算 3 之内，避免 load() 时再次触发压缩耗尽 stub 摘要序列
    budget = ContextBudget(max_context_tokens=3, keep_recent_messages=1)
    memory = make_memory(db_path, price_table, budget, summaries=["summ"])

    for i in range(4):
        await memory.append("s1", msg(i), tenant_id="tenant-a")

    history = await memory.load("s1", tenant_id="tenant-a")
    assert len(history) == 2
    assert history[0].content == "summ"
    assert history[1].content == "msg3"  # 保留窗口内的最近消息未被压缩

    store = SqliteStore(db_path)
    rows = await store.load_rows("tenant-a", "s1")
    assert estimate_total_tokens(rows) <= budget.max_context_tokens
    await store.close()
    await memory.aclose()


async def test_no_compaction_when_under_budget(db_path, price_table):
    budget = ContextBudget(max_context_tokens=4000, keep_recent_messages=6)
    memory = make_memory(db_path, price_table, budget)

    await memory.append("s1", msg(0), tenant_id="tenant-a")
    await memory.append("s1", msg(1), tenant_id="tenant-a")

    history = await memory.load("s1", tenant_id="tenant-a")
    assert [m.content for m in history] == ["msg0", "msg1"]
    await memory.aclose()


async def test_compaction_skipped_when_to_compact_empty(db_path, price_table):
    # keep_recent_messages 覆盖全部消息 -> to_compact 恒为空，即使超预算也不压缩
    budget = ContextBudget(max_context_tokens=1, keep_recent_messages=100)
    memory = make_memory(db_path, price_table, budget)

    await memory.append("s1", Message(role="user", content="x" * 200), tenant_id="tenant-a")

    history = await memory.load("s1", tenant_id="tenant-a")
    assert len(history) == 1  # 未被压缩，尽力而为，不报错
    await memory.aclose()


async def test_compaction_failure_does_not_lose_original_messages(db_path, price_table):
    # 同上，max_context_tokens=3、keep_recent_messages=1：前 3 条 append 不触发压缩
    # （provider 从未被调用），第 4 条 append 触发压缩且 provider 失败
    budget = ContextBudget(max_context_tokens=3, keep_recent_messages=1)
    provider = erroring_provider(httpx.ConnectError("boom"))
    memory = SqliteMemory(db_path=db_path, provider=provider, model=MODEL, budget=budget)

    for i in range(3):
        await memory.append("s1", msg(i), tenant_id="tenant-a")  # 未超预算，正常完成

    with pytest.raises(Exception):
        await memory.append("s1", msg(3), tenant_id="tenant-a")  # 触发压缩，provider 失败

    # 原始 4 条消息（含刚插入、触发压缩失败的第 4 条）应仍完整可读，
    # 未因压缩失败而丢失或处于中间态（FR-007）
    store = SqliteStore(db_path)
    rows = await store.load_rows("tenant-a", "s1")
    assert [r.message.content for r in rows] == ["msg0", "msg1", "msg2", "msg3"]
    await store.close()
    await memory.aclose()
