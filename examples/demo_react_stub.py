"""T020: ReAct 引擎 stub 演示——直接回答 / 工具调用后回答 / 步数耗尽。

运行: python examples/demo_react_stub.py（无需网络与真实模型密钥）
预期输出见 specs/002-react-engine/quickstart.md 第 2 节。
"""

import asyncio
import json

import httpx
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

from kernel.provider import LLMProvider, ModelPrice, PriceTable
from kernel.react import ReactEngine, StepBudgetExceededError

MODEL = "react-demo-model"


def setup_console_tracing() -> None:
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)


def _proxy_payload(content: str) -> dict:
    return {
        "model": MODEL,
        "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
    }


def scripted_transport(responses: list[str]) -> httpx.MockTransport:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        content = queue.pop(0)
        return httpx.Response(200, json=_proxy_payload(content))

    return httpx.MockTransport(handler)


def always_call_tool_transport(tool_name: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        content = json.dumps({"action": "call_tool", "tool": tool_name, "arguments": {}})
        return httpx.Response(200, json=_proxy_payload(content))

    return httpx.MockTransport(handler)


class EchoSearchTool:
    name = "search"
    description = "返回固定的模拟搜索结果"

    async def invoke(self, arguments: dict, *, tenant_id: str) -> str:
        return "模拟搜索结果：答案是 42"


def price_table() -> PriceTable:
    return PriceTable(prices={MODEL: ModelPrice(input_per_1k_usd=0.5, output_per_1k_usd=1.5)})


async def main() -> None:
    setup_console_tracing()

    print("=== 1. 直接回答（无需工具）===")
    provider1 = LLMProvider(
        base_url="http://stub",
        price_table=price_table(),
        transport=scripted_transport(
            [json.dumps({"action": "final_answer", "content": "答案是 42"})]
        ),
    )
    engine1 = ReactEngine(provider=provider1, tools={}, model=MODEL)
    result1 = await engine1.run("不需要工具的问题", tenant_id="tenant-demo", max_steps=5)
    print(f"结果: {result1}\n")

    print("=== 2. 调用工具后回答 ===")
    provider2 = LLMProvider(
        base_url="http://stub",
        price_table=price_table(),
        transport=scripted_transport(
            [
                json.dumps({"action": "call_tool", "tool": "search", "arguments": {"q": "答案"}}),
                json.dumps({"action": "final_answer", "content": "根据搜索，答案是 42"}),
            ]
        ),
    )
    engine2 = ReactEngine(provider=provider2, tools={"search": EchoSearchTool()}, model=MODEL)
    result2 = await engine2.run("需要搜索的问题", tenant_id="tenant-demo", max_steps=5)
    print(f"结果: {result2}\n")

    print("=== 3. 步数耗尽（max_steps=2，永远决定调用工具）===")
    provider3 = LLMProvider(
        base_url="http://stub",
        price_table=price_table(),
        transport=always_call_tool_transport("search"),
    )
    engine3 = ReactEngine(provider=provider3, tools={"search": EchoSearchTool()}, model=MODEL)
    try:
        await engine3.run("永远无法回答的问题", tenant_id="tenant-demo", max_steps=2)
    except StepBudgetExceededError as exc:
        print(f"捕获 {type(exc).__name__}: {exc}\n")

    print("演示完成：每步产生一条 react.step span（见控制台 JSON），"
          "内含的 chat span 为其子 span。")


if __name__ == "__main__":
    asyncio.run(main())
