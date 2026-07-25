"""T025: 真实 LiteLLM proxy 演示（可选，需本地 proxy 运行）。

前置: docker 启动 LiteLLM proxy（见 specs/001 contracts/litellm-proxy-contract.md），
默认地址 http://localhost:4000。

运行: python examples/demo_proxy.py [model-name]
环境变量: LITELLM_BASE_URL / LITELLM_API_KEY 可覆盖默认值。
行为契约与 demo_stub.py 一致。
"""

import asyncio
import os
import sys

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

from kernel.provider import (
    Limits,
    LLMProvider,
    LLMRequest,
    Message,
    ModelPrice,
    PriceTable,
    ProviderError,
)


async def main() -> None:
    model = sys.argv[1] if len(sys.argv) > 1 else "gpt-4o-mini"
    base_url = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000")
    api_key = os.environ.get("LITELLM_API_KEY")

    provider_otel = TracerProvider()
    provider_otel.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider_otel)

    provider = LLMProvider(
        base_url=base_url,
        api_key=api_key,
        # 演示用单价，生产中按实际模型价格配置
        price_table=PriceTable(
            prices={model: ModelPrice(input_per_1k_usd=0.15, output_per_1k_usd=0.6)}
        ),
    )

    request = LLMRequest(
        tenant_id="tenant-demo",
        model=model,
        messages=(Message(role="user", content="用一句话介绍你自己"),),
        limits=Limits(timeout_seconds=30.0, max_total_tokens=1024, max_cost_usd=0.05),
    )

    try:
        response = await provider.complete(request)
        print(f"model={response.model}")
        print(f"content={response.content!r}")
        print(f"usage={response.usage} cost={response.cost_usd:.6f} USD")
    except ProviderError as exc:
        print(f"调用失败（{type(exc).__name__}）: {exc}")
        print(f"请确认 LiteLLM proxy 运行于 {base_url} 且已配置模型 {model!r}")
    finally:
        await provider.aclose()


if __name__ == "__main__":
    asyncio.run(main())
