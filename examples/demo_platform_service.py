"""T026: 平台服务层 REST 入口演示——成功调用、鉴权失败、并发超限、内核失败。

运行: python examples/demo_platform_service.py（无需网络、无需真实模型密钥；
provider 替换为 stub，配置结构与 examples/platform_config.example.json 一致）
预期输出见 specs/007-platform-web-service/quickstart.md 第 2 节。
"""

import asyncio
import json
import tempfile
from pathlib import Path

import httpx
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

from kernel.memory import SqliteMemory
from kernel.memory.long_term import LongTermMemory
from kernel.provider import LLMProvider, ModelPrice, PriceTable
from kernel.tool import ToolRegistry
from platform_service.agent_service import AgentService
from platform_service.app import create_app
from platform_service.config import PlatformConfig, TenantConfig

MODEL = "azure-gpt4o-mini"


def setup_console_tracing() -> None:
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)


def _proxy_payload(content: str) -> dict:
    return {
        "model": MODEL,
        "choices": [
            {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
    }


def stub_provider() -> LLMProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        content = json.dumps({"action": "final_answer", "content": "长沙今天适合穿薄外套。"})
        return httpx.Response(200, json=_proxy_payload(content))

    return LLMProvider(
        base_url="http://stub",
        price_table=PriceTable(prices={MODEL: ModelPrice(0.00015, 0.0006)}),
        transport=httpx.MockTransport(handler),
    )


def slow_stub_provider(delay_seconds: float) -> LLMProvider:
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(delay_seconds)
        content = json.dumps({"action": "final_answer", "content": "长沙今天适合穿薄外套。"})
        return httpx.Response(200, json=_proxy_payload(content))

    return LLMProvider(
        base_url="http://stub",
        price_table=PriceTable(prices={MODEL: ModelPrice(0.00015, 0.0006)}),
        transport=httpx.MockTransport(handler),
    )


def failing_provider() -> LLMProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("模拟的下游模型服务故障")

    return LLMProvider(
        base_url="http://stub",
        price_table=PriceTable(prices={MODEL: ModelPrice(0.00015, 0.0006)}),
        transport=httpx.MockTransport(handler),
    )


def build_demo_config() -> PlatformConfig:
    return PlatformConfig(
        tenants=[
            TenantConfig(api_key="demo-key", tenant_id="tenant-demo", max_concurrent_requests=1),
        ],
        global_max_concurrent_requests=5,
        request_timeout_seconds=10.0,
        model=MODEL,
        max_steps=6,
        provider_base_url="http://stub",
        price_table=PriceTable(prices={MODEL: ModelPrice(0.00015, 0.0006)}),
    )


async def _build_app(config: PlatformConfig, db_dir: Path, provider: LLMProvider):
    session_memory = SqliteMemory(
        db_path=str(db_dir / "session.db"), provider=provider, model=config.model
    )
    long_term_memory = LongTermMemory(
        db_path=str(db_dir / "long_term.db"), provider=provider, model=config.model
    )
    service = AgentService(
        provider=provider,
        tool_registry=ToolRegistry(),
        session_memory=session_memory,
        long_term_memory=long_term_memory,
        config=config,
    )
    app = create_app(config, agent_service=service)
    return app, session_memory, long_term_memory


async def main() -> None:
    setup_console_tracing()
    config = build_demo_config()

    with tempfile.TemporaryDirectory() as tmpdir:
        db_dir = Path(tmpdir)

        print("=== 1. 成功调用 ===")
        app, session_memory, long_term_memory = await _build_app(
            config, db_dir, stub_provider()
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://demo"
        ) as client:
            response = await client.post(
                "/v1/agent/run",
                headers={"X-API-Key": "demo-key"},
                json={"goal": "长沙今天穿什么合适？"},
            )
            print(f"状态码: {response.status_code}, 结果: {response.json()}\n")

            print("=== 2. 鉴权失败（未携带合法 API Key） ===")
            response = await client.post(
                "/v1/agent/run",
                headers={"X-API-Key": "wrong-key"},
                json={"goal": "长沙今天穿什么合适？"},
            )
            print(f"状态码: {response.status_code}, 响应: {response.json()}\n")

        await session_memory.aclose()
        await long_term_memory.aclose()

        print("=== 3. 并发超限（该租户上限为 1，并发发起 2 个请求） ===")
        app, session_memory, long_term_memory = await _build_app(
            config, db_dir, slow_stub_provider(0.5)
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://demo"
        ) as client:
            first = asyncio.create_task(
                client.post(
                    "/v1/agent/run",
                    headers={"X-API-Key": "demo-key"},
                    json={"goal": "问题 A"},
                )
            )
            await asyncio.sleep(0.1)
            second = await client.post(
                "/v1/agent/run",
                headers={"X-API-Key": "demo-key"},
                json={"goal": "问题 B"},
            )
            print(f"第二个并发请求状态码: {second.status_code}, 响应: {second.json()}")
            await first
            print()
        await session_memory.aclose()
        await long_term_memory.aclose()

        print("=== 4. 内核处理失败（下游模型服务故障） ===")
        app, session_memory, long_term_memory = await _build_app(
            config, db_dir, failing_provider()
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://demo"
        ) as client:
            response = await client.post(
                "/v1/agent/run",
                headers={"X-API-Key": "demo-key"},
                json={"goal": "长沙今天穿什么合适？"},
            )
            print(f"状态码: {response.status_code}, 响应: {response.json()}\n")
        await session_memory.aclose()
        await long_term_memory.aclose()

    print("演示完成：每次请求均产生 platform.request span（含 tenant_id/"
          "session_id/result），成功请求的 span 下嵌套内核的 react.step/"
          "chat 等子 span，见控制台 JSON 输出。")


if __name__ == "__main__":
    asyncio.run(main())
