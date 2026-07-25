"""T011 [US1]: 成功调用——统一响应结构、模型透传、成本计算。"""

import pytest

from kernel.provider import LLMProvider, LLMRequest, Message
from tests.unit.provider.conftest import (
    DEFAULT_MODEL,
    echo_request_transport,
    success_payload,
    success_transport,
)


def make_request(**overrides) -> LLMRequest:
    kwargs = dict(
        tenant_id="tenant-a",
        model=DEFAULT_MODEL,
        messages=(Message(role="user", content="hello"),),
    )
    kwargs.update(overrides)
    return LLMRequest(**kwargs)


def make_provider(price_table, transport) -> LLMProvider:
    return LLMProvider(
        base_url="http://stub", price_table=price_table, transport=transport
    )


async def test_success_response_fields_complete(price_table):
    provider = make_provider(price_table, success_transport())
    response = await provider.complete(make_request())

    assert response.content == "hello from stub"
    assert response.model == DEFAULT_MODEL
    assert response.usage.input_tokens == 20
    assert response.usage.output_tokens == 10
    assert response.usage.total_tokens == 30
    assert response.finish_reason == "stop"
    # 20/1000*0.01 + 10/1000*0.03
    assert response.cost_usd == pytest.approx(0.0005)
    await provider.aclose()


async def test_model_passed_through_and_response_model_read_back(price_table):
    captured = []
    provider = make_provider(price_table, echo_request_transport(captured))
    await provider.complete(make_request())
    assert captured[0]["model"] == DEFAULT_MODEL
    assert captured[0]["stream"] is False
    await provider.aclose()


async def test_response_model_may_differ_from_request(price_table):
    payload = success_payload(model=f"{DEFAULT_MODEL}-2026-01-01")
    provider = make_provider(price_table, success_transport(payload))
    response = await provider.complete(make_request())
    assert response.model == f"{DEFAULT_MODEL}-2026-01-01"
    await provider.aclose()


async def test_temperature_sent_only_when_provided(price_table):
    captured = []
    provider = make_provider(price_table, echo_request_transport(captured))
    await provider.complete(make_request())
    await provider.complete(make_request(temperature=0.3))
    assert "temperature" not in captured[0]
    assert captured[1]["temperature"] == 0.3
    await provider.aclose()


async def test_max_tokens_budget_sent(price_table):
    captured = []
    provider = make_provider(price_table, echo_request_transport(captured))
    await provider.complete(make_request())
    # 默认 8192 - 输入粗估（5 字符 // 4 = 1）
    assert captured[0]["max_tokens"] == 8191
    await provider.aclose()
