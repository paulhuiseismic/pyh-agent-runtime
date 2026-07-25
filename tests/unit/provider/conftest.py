"""provider 测试公共设施：MockTransport 响应工厂与 OTel 内存采集 fixture。"""

import asyncio
import json

import httpx
import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from kernel.provider.models import ModelPrice, PriceTable

DEFAULT_MODEL = "gpt-test"


@pytest.fixture
def price_table() -> PriceTable:
    return PriceTable(
        prices={
            DEFAULT_MODEL: ModelPrice(input_per_1k_usd=0.01, output_per_1k_usd=0.03),
            "expensive-model": ModelPrice(input_per_1k_usd=10.0, output_per_1k_usd=30.0),
        }
    )


def success_payload(
    *,
    model: str = DEFAULT_MODEL,
    content: str = "hello from stub",
    prompt_tokens: int = 20,
    completion_tokens: int = 10,
    finish_reason: str = "stop",
) -> dict:
    return {
        "model": model,
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def make_transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def success_transport(payload: dict | None = None) -> httpx.MockTransport:
    """返回固定成功响应；payload 为 None 时用默认成功响应。"""

    def handler(request: httpx.Request) -> httpx.Response:
        body = payload if payload is not None else success_payload()
        return httpx.Response(200, json=body)

    return make_transport(handler)


def echo_request_transport(captured: list) -> httpx.MockTransport:
    """记录发出的请求体，便于断言 max_tokens/temperature 等参数透传。"""

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content.decode()))
        return httpx.Response(200, json=success_payload())

    return make_transport(handler)


def slow_transport(delay_seconds: float) -> httpx.MockTransport:
    """慢响应：用于超时场景。"""

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(delay_seconds)
        return httpx.Response(200, json=success_payload())

    return make_transport(handler)


def connect_error_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    return make_transport(handler)


def http_error_transport(status_code: int, body: str = "upstream error") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=body)

    return make_transport(handler)


def malformed_transport(body: str = "not json") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    return make_transport(handler)


@pytest.fixture
def span_exporter() -> InMemorySpanExporter:
    """每个测试独立的内存 span 采集器（全局 TracerProvider 只允许 set 一次）。"""
    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    yield exporter
    exporter.clear()
