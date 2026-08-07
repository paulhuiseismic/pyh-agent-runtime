"""T017: 消息网关演示——成功投递+异步回调、渠道未识别、重复投递、内核失败。

运行: python examples/demo_message_gateway.py（无需网络、无需真实模型
密钥；provider 与出站回调均替换为 stub，配置结构与
examples/platform_config.example.json 一致）
预期输出见 specs/009-message-channels/quickstart.md。
"""

import asyncio
import json

import httpx

from kernel.memory import SqliteMemory
from kernel.memory.long_term import LongTermMemory
from kernel.provider import LLMProvider, ModelPrice, PriceTable
from kernel.tool import ToolRegistry
from platform_service.agent_service import AgentService
from platform_service.config import ChannelConfig, PlatformConfig, TenantConfig
from platform_service.message_gateway import build_message_gateway
from platform_service.models import InboundMessage

MODEL = "azure-gpt4o-mini"


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


def failing_provider() -> LLMProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("模拟的下游模型服务故障")

    return LLMProvider(
        base_url="http://stub",
        price_table=PriceTable(prices={MODEL: ModelPrice(0.00015, 0.0006)}),
        transport=httpx.MockTransport(handler),
    )


def recording_callback_client() -> tuple[httpx.AsyncClient, list[dict]]:
    received: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), received


def build_demo_config() -> PlatformConfig:
    return PlatformConfig(
        tenants=[
            TenantConfig(api_key="demo-key", tenant_id="tenant-demo", max_concurrent_requests=5),
        ],
        global_max_concurrent_requests=10,
        request_timeout_seconds=10.0,
        model=MODEL,
        max_steps=6,
        provider_base_url="http://stub",
        price_table=PriceTable(prices={MODEL: ModelPrice(0.00015, 0.0006)}),
        channels=[
            ChannelConfig(
                channel_id="demo-channel",
                tenant_id="tenant-demo",
                callback_url="http://callback.stub/receive",
            )
        ],
    )


async def _build_gateway(config: PlatformConfig, provider: LLMProvider):
    session_memory = SqliteMemory(db_path=":memory:", provider=provider, model=config.model)
    long_term_memory = LongTermMemory(db_path=":memory:", provider=provider, model=config.model)
    agent_service = AgentService(
        provider=provider,
        tool_registry=ToolRegistry(),
        session_memory=session_memory,
        long_term_memory=long_term_memory,
        config=config,
    )
    callback_client, received = recording_callback_client()
    gateway = await build_message_gateway(
        config, agent_service=agent_service, callback_client=callback_client
    )
    return gateway, received, session_memory, long_term_memory, callback_client


def _message(**overrides) -> InboundMessage:
    payload = dict(
        channel_id="demo-channel",
        external_message_id="msg-1",
        sender="user-1",
        text="长沙今天穿什么合适？",
    )
    payload.update(overrides)
    return InboundMessage(**payload)


async def main() -> None:
    config = build_demo_config()

    print("=== 1. 成功投递 + 异步回调 ===")
    gateway, received, session_memory, long_term_memory, callback_client = await _build_gateway(
        config, stub_provider()
    )
    result = await gateway.handle_inbound(_message())
    print(f"接入响应: accepted={result.accepted}, duplicate={result.duplicate}")
    await gateway.wait_for_background_tasks()
    print(f"收到的出站回调: {received[-1]}")
    await session_memory.aclose()
    await long_term_memory.aclose()
    await callback_client.aclose()

    print("\n=== 2. 渠道未识别 ===")
    gateway, received, session_memory, long_term_memory, callback_client = await _build_gateway(
        config, stub_provider()
    )
    try:
        await gateway.handle_inbound(_message(channel_id="unknown-channel"))
    except Exception as exc:
        print(f"拒绝: {exc}")
    await gateway.wait_for_background_tasks()
    print(f"出站回调调用次数: {len(received)}")
    await session_memory.aclose()
    await long_term_memory.aclose()
    await callback_client.aclose()

    print("\n=== 3. 重复投递 ===")
    gateway, received, session_memory, long_term_memory, callback_client = await _build_gateway(
        config, stub_provider()
    )
    first = await gateway.handle_inbound(_message())
    await gateway.wait_for_background_tasks()
    second = await gateway.handle_inbound(_message())
    await gateway.wait_for_background_tasks()
    print(f"第一次 duplicate={first.duplicate}, 第二次 duplicate={second.duplicate}")
    print(f"出站回调调用次数: {len(received)}（应为 1）")
    await session_memory.aclose()
    await long_term_memory.aclose()
    await callback_client.aclose()

    print("\n=== 4. 内核处理失败 ===")
    gateway, received, session_memory, long_term_memory, callback_client = await _build_gateway(
        config, failing_provider()
    )
    await gateway.handle_inbound(_message())
    await gateway.wait_for_background_tasks()
    print(f"收到的出站回调: {received[-1]}")
    await session_memory.aclose()
    await long_term_memory.aclose()
    await callback_client.aclose()

    print(
        "\n演示完成：四种场景的接入响应与出站回调内容如上；成功场景会产生"
        " platform.request span（内含 react.step/chat 等内核子 span），"
        "渠道未识别场景不产生任何 span（复用 007/008 telemetry 实现）。"
    )


if __name__ == "__main__":
    asyncio.run(main())
