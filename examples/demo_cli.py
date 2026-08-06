"""T013: CLI 入口演示——成功调用、缺少 API Key、身份识别失败、内核失败。

运行: python examples/demo_cli.py（无需网络、无需真实模型密钥；provider
替换为 stub，配置结构与 examples/platform_config.example.json 一致）
预期输出见 specs/008-cli-entrypoint/quickstart.md。
"""

import asyncio
import json
import tempfile
from pathlib import Path

import httpx

from kernel.memory import SqliteMemory
from kernel.memory.long_term import LongTermMemory
from kernel.provider import LLMProvider, ModelPrice, PriceTable
from kernel.tool import ToolRegistry
from platform_service import cli
from platform_service.agent_service import AgentService
from platform_service.config import PlatformConfig, TenantConfig

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


def _write_config_file(path: Path, config: PlatformConfig) -> None:
    payload = {
        "tenants": [
            {
                "api_key": t.api_key,
                "tenant_id": t.tenant_id,
                "max_concurrent_requests": t.max_concurrent_requests,
            }
            for t in config.tenants
        ],
        "global_max_concurrent_requests": config.global_max_concurrent_requests,
        "request_timeout_seconds": config.request_timeout_seconds,
        "model": config.model,
        "max_steps": config.max_steps,
        "provider_base_url": config.provider_base_url,
        "price_table": {
            MODEL: {"input_per_1k_usd": 0.00015, "output_per_1k_usd": 0.0006},
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


async def _build_service(config: PlatformConfig, provider: LLMProvider):
    session_memory = SqliteMemory(db_path=":memory:", provider=provider, model=config.model)
    long_term_memory = LongTermMemory(db_path=":memory:", provider=provider, model=config.model)
    service = AgentService(
        provider=provider,
        tool_registry=ToolRegistry(),
        session_memory=session_memory,
        long_term_memory=long_term_memory,
        config=config,
    )
    return service, session_memory, long_term_memory


async def main() -> None:
    config = build_demo_config()

    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "config.json"
        _write_config_file(config_path, config)
        base_env = {"PLATFORM_SERVICE_CONFIG": str(config_path)}

        print("=== 1. 成功调用 ===")
        service, session_memory, long_term_memory = await _build_service(config, stub_provider())
        exit_code, stdout, stderr = await cli.run(
            ["长沙今天穿什么合适？"],
            {**base_env, "PLATFORM_SERVICE_API_KEY": "demo-key"},
            agent_service=service,
        )
        print(f"退出码: {exit_code}, 输出: {stdout!r}")

        print("\n=== 2. 缺少 API Key ===")
        exit_code, stdout, stderr = await cli.run(
            ["长沙今天穿什么合适？"],
            base_env,
            agent_service=service,
        )
        print(f"退出码: {exit_code}, stderr: {stderr!r}")

        print("\n=== 3. 身份识别失败（API Key 不匹配任何租户） ===")
        exit_code, stdout, stderr = await cli.run(
            ["长沙今天穿什么合适？"],
            {**base_env, "PLATFORM_SERVICE_API_KEY": "wrong-key"},
            agent_service=service,
        )
        print(f"退出码: {exit_code}, stderr: {stderr!r}")
        await session_memory.aclose()
        await long_term_memory.aclose()

        print("\n=== 4. 内核处理失败（下游模型服务故障） ===")
        service, session_memory, long_term_memory = await _build_service(
            config, failing_provider()
        )
        exit_code, stdout, stderr = await cli.run(
            ["长沙今天穿什么合适？"],
            {**base_env, "PLATFORM_SERVICE_API_KEY": "demo-key"},
            agent_service=service,
        )
        print(f"退出码: {exit_code}, stderr: {stderr!r}")
        await session_memory.aclose()
        await long_term_memory.aclose()

    print(
        "\n演示完成：四种场景的退出码与输出内容如上；成功场景会产生"
        " platform.request span（内含 react.step/chat 等内核子 span），"
        "鉴权失败场景不产生任何 span（复用 007 telemetry 实现）。"
    )


if __name__ == "__main__":
    asyncio.run(main())
