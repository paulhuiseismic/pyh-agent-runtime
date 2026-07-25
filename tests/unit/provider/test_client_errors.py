"""T016 [US2]: 连接失败与畸形响应的错误映射（边界场景）。"""

import pytest

from kernel.provider import (
    LLMProvider,
    LLMRequest,
    MalformedResponseError,
    Message,
    ProxyConnectionError,
)
from tests.unit.provider.conftest import (
    DEFAULT_MODEL,
    connect_error_transport,
    http_error_transport,
    make_transport,
    malformed_transport,
    success_payload,
)
import httpx


def make_request() -> LLMRequest:
    return LLMRequest(
        tenant_id="tenant-a",
        model=DEFAULT_MODEL,
        messages=(Message(role="user", content="hi"),),
    )


def make_provider(price_table, transport) -> LLMProvider:
    return LLMProvider(
        base_url="http://stub", price_table=price_table, transport=transport
    )


async def test_connection_refused_maps_and_no_retry(price_table):
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        raise httpx.ConnectError("connection refused")

    provider = make_provider(price_table, make_transport(handler))
    with pytest.raises(ProxyConnectionError):
        await provider.complete(make_request())
    assert len(attempts) == 1  # 不自动重试
    await provider.aclose()


async def test_http_500_maps_with_status_code(price_table):
    provider = make_provider(price_table, http_error_transport(500, "boom"))
    with pytest.raises(ProxyConnectionError) as exc_info:
        await provider.complete(make_request())
    assert exc_info.value.status_code == 500
    assert "boom" in exc_info.value.detail
    await provider.aclose()


async def test_http_401_maps_with_status_code(price_table):
    provider = make_provider(price_table, http_error_transport(401))
    with pytest.raises(ProxyConnectionError) as exc_info:
        await provider.complete(make_request())
    assert exc_info.value.status_code == 401
    await provider.aclose()


async def test_non_json_response_malformed(price_table):
    provider = make_provider(price_table, malformed_transport("not json"))
    with pytest.raises(MalformedResponseError):
        await provider.complete(make_request())
    await provider.aclose()


@pytest.mark.parametrize("missing_key", ["choices", "usage", "model"])
async def test_missing_required_field_malformed(price_table, missing_key):
    payload = success_payload()
    payload.pop(missing_key)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    provider = make_provider(price_table, make_transport(handler))
    with pytest.raises(MalformedResponseError):
        await provider.complete(make_request())
    await provider.aclose()
