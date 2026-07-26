"""T021: 长期记忆 stub 演示——提炼写入 / 查询 / 同类别覆盖 / 跨租户隔离。

运行: python examples/demo_long_term_memory_stub.py（无需网络与真实模型密钥）
预期输出见 specs/004-long-term-memory/quickstart.md 第 2 节。
"""

import asyncio
import json
import tempfile
from pathlib import Path

import httpx
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

from kernel.memory import LongTermMemory
from kernel.provider import LLMProvider, Message, ModelPrice, PriceTable

MODEL = "long-term-demo-model"


def setup_console_tracing() -> None:
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)


def make_provider(payload_by_marker: dict[str, str]) -> LLMProvider:
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

    return LLMProvider(
        base_url="http://stub",
        price_table=PriceTable(prices={MODEL: ModelPrice(0.01, 0.03)}),
        transport=httpx.MockTransport(handler),
    )


async def main() -> None:
    setup_console_tracing()

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "long_term_demo.db")

        payloads = {
            "对话1: 我更喜欢简洁的回答": json.dumps(
                [{"category": "response_style", "content": "偏好简洁的回答"}]
            ),
            "对话2: 其实我更想要详细一点的解释": json.dumps(
                [{"category": "response_style", "content": "偏好详细的回答"}]
            ),
            "对话3: 我平时喜欢吃辣的菜": json.dumps(
                [{"category": "food", "content": "喜欢吃辣"}]
            ),
        }
        provider = make_provider(payloads)
        memory = LongTermMemory(db_path=db_path, provider=provider, model=MODEL)

        print("=== 1. 提炼写入 ===")
        await memory.extract(
            (Message(role="user", content="对话1: 我更喜欢简洁的回答"),), tenant_id="tenant-demo"
        )
        stored = await memory.query(tenant_id="tenant-demo")
        print(f"写入后查询: {[(e.category, e.content) for e in stored]}\n")

        print("=== 2. 同类别提炼覆盖旧条目 ===")
        await memory.extract(
            (Message(role="user", content="对话2: 其实我更想要详细一点的解释"),),
            tenant_id="tenant-demo",
        )
        stored = await memory.query(tenant_id="tenant-demo")
        print(f"覆盖后查询（response_style 仍只有一条）: {[(e.category, e.content) for e in stored]}\n")

        print("=== 3. 不同类别独立新增 ===")
        await memory.extract(
            (Message(role="user", content="对话3: 我平时喜欢吃辣的菜"),), tenant_id="tenant-demo"
        )
        stored = await memory.query(tenant_id="tenant-demo")
        print(f"新增后查询: {[(e.category, e.content) for e in stored]}\n")

        print("=== 4. 跨租户隔离 ===")
        stored_other = await memory.query(tenant_id="tenant-other")
        print(f"另一租户查询结果: {stored_other}\n")

        await memory.aclose()

    print("演示完成：每次 extract/query 各产生一条 long_term_memory.<operation> span，"
          "extract 触发的 span 下挂载 chat 子 span（见控制台 JSON 输出）。")


if __name__ == "__main__":
    asyncio.run(main())
