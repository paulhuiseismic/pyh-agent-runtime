"""T024: stub 演示——成功调用 / 超时 / 成本超限，span 输出到控制台。

运行: python examples/demo_stub.py（无需网络与真实模型密钥）
预期输出见 specs/001-kernel-provider/quickstart.md 第 2 节。
"""

import asyncio

import httpx
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

from kernel.provider import (
    CallTimeoutError,
    CostLimitExceededError,
    Limits,
    LLMProvider,
    LLMRequest,
    Message,
    ModelPrice,
    PriceTable,
)

MODEL = "gpt-demo"


def setup_console_tracing() -> None:
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)


def stub_transport() -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content.decode())
        marker = body["messages"][0]["content"]
        if marker == "slow":
            await asyncio.sleep(10)
        completion_tokens = 100_000 if marker == "big" else 12
        return httpx.Response(
            200,
            json={
                "model": MODEL,
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "你好，我是 stub 模型。"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 8,
                    "completion_tokens": completion_tokens,
                    "total_tokens": 8 + completion_tokens,
                },
            },
        )

    return httpx.MockTransport(handler)


async def main() -> None:
    setup_console_tracing()
    provider = LLMProvider(
        base_url="http://stub.local",
        price_table=PriceTable(
            prices={MODEL: ModelPrice(input_per_1k_usd=0.5, output_per_1k_usd=1.5)}
        ),
        transport=stub_transport(),
    )

    def request(content: str, limits: Limits | None = None) -> LLMRequest:
        return LLMRequest(
            tenant_id="tenant-demo",
            model=MODEL,
            messages=(Message(role="user", content=content),),
            limits=limits,
        )

    print("=== 1. 成功调用 ===")
    response = await provider.complete(request("你好"))
    print(f"content={response.content!r}")
    print(f"usage={response.usage}")
    print(f"cost_usd={response.cost_usd:.6f}\n")

    print("=== 2. 超时调用（timeout=0.5s，stub 延迟 10s）===")
    try:
        await provider.complete(request("slow", Limits(timeout_seconds=0.5)))
    except CallTimeoutError as exc:
        print(f"捕获 {type(exc).__name__}: {exc}\n")

    print("=== 3. 成本超限调用（上限 0.01 USD）===")
    try:
        await provider.complete(
            request("big", Limits(max_cost_usd=0.01, max_total_tokens=200_000))
        )
    except CostLimitExceededError as exc:
        print(f"捕获 {type(exc).__name__}: {exc}\n")

    await provider.aclose()
    print("演示完成：以上每次调用各产生一条 span（见控制台 JSON 输出，含 tenant_id）。")


if __name__ == "__main__":
    asyncio.run(main())
