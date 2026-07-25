"""T012 [US1]: 参数校验——发出前拒绝，不产生 HTTP 请求。"""

import httpx
import pytest

from kernel.provider import (
    InvalidRequestError,
    Limits,
    LLMProvider,
    LLMRequest,
    Message,
)
from tests.unit.provider.conftest import DEFAULT_MODEL, make_transport


def counting_transport(counter: list) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        counter.append(request)
        return httpx.Response(500)

    return make_transport(handler)


async def test_missing_tenant_rejected_before_any_http(price_table):
    counter = []
    provider = LLMProvider(
        base_url="http://stub",
        price_table=price_table,
        transport=counting_transport(counter),
    )
    with pytest.raises(InvalidRequestError):
        LLMRequest(
            tenant_id="  ",
            model=DEFAULT_MODEL,
            messages=(Message(role="user", content="hi"),),
        )
    assert counter == []  # 构造即拒绝，未发出任何请求
    await provider.aclose()


async def test_unknown_model_rejected_before_any_http(price_table):
    counter = []
    provider = LLMProvider(
        base_url="http://stub",
        price_table=price_table,
        transport=counting_transport(counter),
    )
    request = LLMRequest(
        tenant_id="tenant-a",
        model="model-without-price",
        messages=(Message(role="user", content="hi"),),
    )
    with pytest.raises(InvalidRequestError, match="单价"):
        await provider.complete(request)
    assert counter == []
    await provider.aclose()


def test_invalid_limits_rejected():
    with pytest.raises(InvalidRequestError):
        Limits(timeout_seconds=0)


def test_empty_messages_rejected():
    with pytest.raises(InvalidRequestError):
        LLMRequest(tenant_id="t", model=DEFAULT_MODEL, messages=())
