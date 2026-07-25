"""react 测试公共设施：脚本化 stub provider 与 stub tool（见 specs/002 research.md R6）。"""

import json

import httpx
import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from kernel.provider import LLMProvider, ModelPrice, PriceTable

MODEL = "react-test-model"


@pytest.fixture
def price_table() -> PriceTable:
    return PriceTable(prices={MODEL: ModelPrice(input_per_1k_usd=0.01, output_per_1k_usd=0.03)})


def _proxy_payload(content: str) -> dict:
    return {
        "model": MODEL,
        "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
    }


def scripted_provider(price_table: PriceTable, responses: list[str]) -> LLMProvider:
    """按调用顺序依次返回 responses 中的 JSON 字符串；超出序列长度则报错。"""
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        if not queue:
            raise AssertionError("stub provider 响应序列已耗尽，调用次数超出预期")
        content = queue.pop(0)
        return httpx.Response(200, json=_proxy_payload(content))

    return LLMProvider(
        base_url="http://stub",
        price_table=price_table,
        transport=httpx.MockTransport(handler),
    )


def always_call_tool_provider(price_table: PriceTable, tool_name: str = "search") -> LLMProvider:
    """永远决定调用工具，用于步数耗尽场景（响应序列无限长）。"""

    def handler(request: httpx.Request) -> httpx.Response:
        content = json.dumps({"action": "call_tool", "tool": tool_name, "arguments": {}})
        return httpx.Response(200, json=_proxy_payload(content))

    return LLMProvider(
        base_url="http://stub",
        price_table=price_table,
        transport=httpx.MockTransport(handler),
    )


def erroring_provider(exc: Exception) -> LLMProvider:
    """每次调用都抛出给定异常的 transport，用于 provider 异常边界测试。"""

    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    return LLMProvider(
        base_url="http://stub",
        price_table=PriceTable(prices={MODEL: ModelPrice(0.01, 0.03)}),
        transport=httpx.MockTransport(handler),
    )


class StubTool:
    """可配置返回值或抛异常的 stub 工具。"""

    def __init__(self, name: str, *, result: str | None = None, raises: Exception | None = None):
        self.name = name
        self.description = f"stub tool {name}"
        self._result = result
        self._raises = raises
        self.call_count = 0
        self.last_arguments: dict | None = None

    async def invoke(self, arguments: dict, *, tenant_id: str) -> str:
        self.call_count += 1
        self.last_arguments = arguments
        if self._raises is not None:
            raise self._raises
        return self._result or ""


@pytest.fixture
def span_exporter():
    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    yield exporter
    exporter.clear()
