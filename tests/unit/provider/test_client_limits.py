"""T015 [US2]: 超时/token/成本超限——类型化失败，携带实际值与上限值。"""

import time

import pytest

from kernel.provider import (
    CallTimeoutError,
    CostLimitExceededError,
    Limits,
    LLMProvider,
    LLMRequest,
    Message,
    TokenLimitExceededError,
)
from tests.unit.provider.conftest import (
    DEFAULT_MODEL,
    slow_transport,
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


def make_provider(price_table, transport, **kwargs) -> LLMProvider:
    return LLMProvider(
        base_url="http://stub", price_table=price_table, transport=transport, **kwargs
    )


async def test_timeout_terminates_within_1_5x_and_raises(price_table):
    timeout = 0.2
    provider = make_provider(price_table, slow_transport(delay_seconds=5.0))
    request = make_request(limits=Limits(timeout_seconds=timeout))

    start = time.monotonic()
    with pytest.raises(CallTimeoutError) as exc_info:
        await provider.complete(request)
    elapsed = time.monotonic() - start

    assert elapsed < timeout * 1.5  # SC-003 口径：1.5 倍时间内必然终止
    assert exc_info.value.timeout_seconds == timeout
    await provider.aclose()


async def test_token_limit_exceeded_with_actual_and_limit(price_table):
    payload = success_payload(prompt_tokens=100, completion_tokens=200)  # total 300
    provider = make_provider(price_table, success_transport(payload))
    request = make_request(limits=Limits(max_total_tokens=250))

    with pytest.raises(TokenLimitExceededError) as exc_info:
        await provider.complete(request)
    assert exc_info.value.actual_tokens == 300
    assert exc_info.value.max_total_tokens == 250
    await provider.aclose()


async def test_cost_limit_exceeded_with_actual_and_limit(price_table):
    # expensive-model: 1000/1000*10 + 1000/1000*30 = 40 USD
    payload = success_payload(
        model="expensive-model", prompt_tokens=1000, completion_tokens=1000
    )
    provider = make_provider(price_table, success_transport(payload))
    request = make_request(
        model="expensive-model", limits=Limits(max_cost_usd=1.0)
    )

    with pytest.raises(CostLimitExceededError) as exc_info:
        await provider.complete(request)
    assert exc_info.value.actual_cost_usd == pytest.approx(40.0)
    assert exc_info.value.max_cost_usd == 1.0
    await provider.aclose()


async def test_default_limits_applied_when_not_specified(price_table):
    provider = make_provider(price_table, success_transport())
    response = await provider.complete(make_request(limits=None))
    assert response.content  # 正常完成即说明默认限额生效且未误伤
    await provider.aclose()


async def test_oversized_input_rejected_before_http(price_table):
    provider = make_provider(price_table, success_transport())
    big_content = "x" * 4000  # 粗估 1000 tokens >= 上限 100
    request = make_request(
        messages=(Message(role="user", content=big_content),),
        limits=Limits(max_total_tokens=100),
    )
    with pytest.raises(TokenLimitExceededError) as exc_info:
        await provider.complete(request)
    assert exc_info.value.max_total_tokens == 100
    await provider.aclose()
