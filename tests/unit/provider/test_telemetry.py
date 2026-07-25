"""T019 [US3]: span 属性契约、失败调用 span、遥测失败不影响调用、并发互不串扰。"""

import asyncio

import httpx
import pytest
from opentelemetry.trace import StatusCode

from kernel.provider import (
    CallTimeoutError,
    InvalidRequestError,
    Limits,
    LLMProvider,
    LLMRequest,
    Message,
    TokenLimitExceededError,
)
from tests.unit.provider.conftest import (
    DEFAULT_MODEL,
    make_transport,
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


def make_provider(price_table, transport) -> LLMProvider:
    return LLMProvider(
        base_url="http://stub", price_table=price_table, transport=transport
    )


async def test_success_span_attributes_complete(price_table, span_exporter):
    provider = make_provider(price_table, success_transport())
    await provider.complete(make_request())

    spans = span_exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == f"chat {DEFAULT_MODEL}"
    assert span.attributes["tenant_id"] == "tenant-a"
    assert span.attributes["gen_ai.operation.name"] == "chat"
    assert span.attributes["gen_ai.request.model"] == DEFAULT_MODEL
    assert span.attributes["gen_ai.response.model"] == DEFAULT_MODEL
    assert span.attributes["gen_ai.usage.input_tokens"] == 20
    assert span.attributes["gen_ai.usage.output_tokens"] == 10
    assert span.attributes["gen_ai.usage.cost"] == pytest.approx(0.0005)
    assert span.status.status_code == StatusCode.OK
    await provider.aclose()


async def test_timeout_failure_span_marked_error(price_table, span_exporter):
    provider = make_provider(price_table, slow_transport(5.0))
    with pytest.raises(CallTimeoutError):
        await provider.complete(
            make_request(limits=Limits(timeout_seconds=0.1))
        )
    spans = span_exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].status.status_code == StatusCode.ERROR
    assert spans[0].attributes["error.type"] == "CallTimeoutError"
    assert spans[0].attributes["tenant_id"] == "tenant-a"
    await provider.aclose()


async def test_pre_flight_rejection_also_produces_span(price_table, span_exporter):
    provider = make_provider(price_table, success_transport())
    with pytest.raises(InvalidRequestError):
        await provider.complete(make_request(model="no-price-model"))
    spans = span_exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].status.status_code == StatusCode.ERROR
    assert spans[0].attributes["error.type"] == "InvalidRequestError"
    await provider.aclose()


async def test_telemetry_failure_does_not_affect_call(
    price_table, span_exporter, monkeypatch
):
    from kernel.provider import telemetry

    class BrokenTracer:
        def start_span(self, *args, **kwargs):
            raise RuntimeError("telemetry backend down")

    monkeypatch.setattr(telemetry, "_tracer", BrokenTracer())
    provider = make_provider(price_table, success_transport())
    response = await provider.complete(make_request())  # 不应抛遥测异常
    assert response.content == "hello from stub"
    await provider.aclose()


async def test_concurrent_calls_do_not_interfere(price_table, span_exporter):
    """并发用例：span 归属正确 + 各自超时/限额结果互不影响。"""

    async def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content.decode())
        tenant_marker = body["messages"][0]["content"]
        if tenant_marker == "slow":
            await asyncio.sleep(5.0)
        if tenant_marker == "big":
            return httpx.Response(
                200, json=success_payload(prompt_tokens=500, completion_tokens=500)
            )
        return httpx.Response(200, json=success_payload())

    provider = make_provider(price_table, make_transport(handler))

    ok_req = make_request(
        tenant_id="tenant-ok",
        messages=(Message(role="user", content="fine"),),
    )
    slow_req = make_request(
        tenant_id="tenant-slow",
        messages=(Message(role="user", content="slow"),),
        limits=Limits(timeout_seconds=0.2),
    )
    big_req = make_request(
        tenant_id="tenant-big",
        messages=(Message(role="user", content="big"),),
        limits=Limits(max_total_tokens=600),
    )

    results = await asyncio.gather(
        provider.complete(ok_req),
        provider.complete(slow_req),
        provider.complete(big_req),
        return_exceptions=True,
    )

    # 各自的限额结果互不影响
    assert results[0].content == "hello from stub"
    assert isinstance(results[1], CallTimeoutError)
    assert isinstance(results[2], TokenLimitExceededError)

    # span 归属正确：每个租户一条，状态各自独立
    spans = span_exporter.get_finished_spans()
    by_tenant = {s.attributes["tenant_id"]: s for s in spans}
    assert set(by_tenant) == {"tenant-ok", "tenant-slow", "tenant-big"}
    assert by_tenant["tenant-ok"].status.status_code == StatusCode.OK
    assert by_tenant["tenant-slow"].attributes["error.type"] == "CallTimeoutError"
    assert by_tenant["tenant-big"].attributes["error.type"] == "TokenLimitExceededError"
    await provider.aclose()
