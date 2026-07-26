"""T020: memory stub 演示——持久化读写 / 跨租户隔离 / 自动压缩。

运行: python examples/demo_memory_stub.py（无需网络与真实模型密钥）
预期输出见 specs/003-memory-compression/quickstart.md 第 2 节。
"""

import asyncio
import json
import tempfile
from pathlib import Path

import httpx
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

from kernel.memory import ContextBudget, SqliteMemory
from kernel.provider import LLMProvider, Message, ModelPrice, PriceTable

MODEL = "memory-demo-model"


def setup_console_tracing() -> None:
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)


def make_provider(summaries: list[str]) -> LLMProvider:
    queue = list(summaries)

    def handler(request: httpx.Request) -> httpx.Response:
        content = queue.pop(0) if queue else "（无更多摘要）"
        return httpx.Response(
            200,
            json={
                "model": MODEL,
                "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
            },
        )

    return LLMProvider(
        base_url="http://stub",
        price_table=PriceTable(prices={MODEL: ModelPrice(0.01, 0.03)}),
        transport=httpx.MockTransport(handler),
    )


async def main() -> None:
    setup_console_tracing()

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "demo.db")

        print("=== 1. 持久化读写 ===")
        provider1 = make_provider([])
        memory1 = SqliteMemory(db_path=db_path, provider=provider1, model=MODEL)
        await memory1.append("s1", Message(role="user", content="你好"), tenant_id="tenant-demo")
        await memory1.append("s1", Message(role="assistant", content="你好，有什么可以帮你？"), tenant_id="tenant-demo")
        await memory1.aclose()

        provider1b = make_provider([])
        memory1b = SqliteMemory(db_path=db_path, provider=provider1b, model=MODEL)
        history = await memory1b.load("s1", tenant_id="tenant-demo")
        print(f"重新打开连接后读取: {[m.content for m in history]}\n")
        await memory1b.aclose()

        print("=== 2. 跨租户隔离 ===")
        provider2 = make_provider([])
        memory2 = SqliteMemory(db_path=db_path, provider=provider2, model=MODEL)
        await memory2.append("shared-session", Message(role="user", content="来自租户 A"), tenant_id="tenant-a")
        await memory2.append("shared-session", Message(role="user", content="来自租户 B"), tenant_id="tenant-b")
        history_a = await memory2.load("shared-session", tenant_id="tenant-a")
        history_b = await memory2.load("shared-session", tenant_id="tenant-b")
        print(f"租户 A 看到: {[m.content for m in history_a]}")
        print(f"租户 B 看到: {[m.content for m in history_b]}\n")
        await memory2.aclose()

        print("=== 3. 超预算自动压缩 ===")
        budget = ContextBudget(max_context_tokens=3, keep_recent_messages=1)
        provider3 = make_provider(["早期对话摘要"])
        memory3 = SqliteMemory(db_path=db_path, provider=provider3, model=MODEL, budget=budget)
        for i in range(4):
            await memory3.append("s2", Message(role="user", content=f"msg{i}"), tenant_id="tenant-demo")
        history3 = await memory3.load("s2", tenant_id="tenant-demo")
        print(f"压缩后历史: {[m.content for m in history3]}")
        await memory3.aclose()

    print("\n演示完成：以上每次 load/append 各产生一条 memory.<operation> span，"
          "触发压缩时其下挂载 chat 子 span（见控制台 JSON 输出）。")


if __name__ == "__main__":
    asyncio.run(main())
