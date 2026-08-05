"""platform_service 测试公共设施：示例配置、stub LLMProvider（复用 001
httpx.MockTransport 模式）。"""

import asyncio
import json

import httpx
import pytest

from kernel.provider import LLMProvider, ModelPrice, PriceTable
from platform_service.config import PlatformConfig, TenantConfig

MODEL = "platform-test-model"


def _proxy_payload(content: str) -> dict:
    return {
        "model": MODEL,
        "choices": [
            {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
    }


def _final_answer_content(answer: str) -> str:
    return json.dumps({"action": "final_answer", "content": answer})


@pytest.fixture
def price_table() -> PriceTable:
    return PriceTable(prices={MODEL: ModelPrice(input_per_1k_usd=0.01, output_per_1k_usd=0.03)})


def stub_provider(answer: str = "42") -> LLMProvider:
    """立即返回固定 final_answer 的 stub provider（复用 001 MockTransport 模式）。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_proxy_payload(_final_answer_content(answer)))

    return LLMProvider(
        base_url="http://stub",
        price_table=PriceTable(prices={MODEL: ModelPrice(0.01, 0.03)}),
        transport=httpx.MockTransport(handler),
    )


def slow_stub_provider(delay_seconds: float, answer: str = "42") -> LLMProvider:
    """延迟 delay_seconds 后返回固定 final_answer，用于并发/超时测试。"""

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(delay_seconds)
        return httpx.Response(200, json=_proxy_payload(_final_answer_content(answer)))

    return LLMProvider(
        base_url="http://stub",
        price_table=PriceTable(prices={MODEL: ModelPrice(0.01, 0.03)}),
        transport=httpx.MockTransport(handler),
    )


def erroring_provider(exc: Exception) -> LLMProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    return LLMProvider(
        base_url="http://stub",
        price_table=PriceTable(prices={MODEL: ModelPrice(0.01, 0.03)}),
        transport=httpx.MockTransport(handler),
    )


@pytest.fixture
def platform_config(price_table) -> PlatformConfig:
    return PlatformConfig(
        tenants=[
            TenantConfig(api_key="key-a", tenant_id="tenant-a", max_concurrent_requests=2),
            TenantConfig(api_key="key-b", tenant_id="tenant-b", max_concurrent_requests=2),
        ],
        global_max_concurrent_requests=10,
        request_timeout_seconds=5.0,
        model=MODEL,
        max_steps=5,
        provider_base_url="http://stub",
        price_table=price_table,
    )
