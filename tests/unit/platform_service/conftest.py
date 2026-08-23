"""platform_service 测试公共设施：示例配置、stub LLMProvider（复用 001
httpx.MockTransport 模式）。"""

import asyncio
import dataclasses
import json
import tempfile
from pathlib import Path

import httpx
import pytest

from kernel.provider import LLMProvider, ModelPrice, PriceTable
from platform_service.audit import AuditStore
from platform_service.config import ChannelConfig, PlatformConfig, TenantConfig

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
def channel_config() -> ChannelConfig:
    return ChannelConfig(
        channel_id="demo-channel",
        tenant_id="tenant-a",
        callback_url="http://callback.test/receive",
    )


def recording_callback_client() -> tuple[httpx.AsyncClient, list[dict]]:
    """返回一个记录每次收到的回调 JSON body 的 httpx.AsyncClient（复用
    httpx.MockTransport 模式）。"""
    received: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), received


def failing_callback_client(call_counter: list[int]) -> httpx.AsyncClient:
    """恒定失败的回调 client，call_counter[0] 记录被调用次数。"""

    def handler(request: httpx.Request) -> httpx.Response:
        call_counter.append(1)
        return httpx.Response(500, json={"error": "callback endpoint down"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture
async def audit_store():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = AuditStore(str(Path(tmpdir) / "audit.db"))
        yield store
        await store.aclose()


def platform_config_with_quota(platform_config: PlatformConfig, tenant_id: str, quota_usd: float) -> PlatformConfig:
    """把 platform_config 中指定租户替换为携带 daily_cost_quota_usd 的版本。"""
    tenants = [
        dataclasses.replace(t, daily_cost_quota_usd=quota_usd) if t.tenant_id == tenant_id else t
        for t in platform_config.tenants
    ]
    return dataclasses.replace(platform_config, tenants=tenants)


class _BrokenAuditStore(AuditStore):
    async def record(self, entry):
        raise RuntimeError("audit store unavailable")


def broken_audit_store() -> AuditStore:
    return _BrokenAuditStore(":memory:")


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
