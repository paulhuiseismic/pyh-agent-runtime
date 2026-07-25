"""T017: provider 异常边界——原样上抛，不被吞成观察结果、不算步数耗尽。"""

import httpx
import pytest

from kernel.provider import ProxyConnectionError, TokenLimitExceededError
from kernel.provider.models import Limits
from kernel.react import ReactEngine, StepBudgetExceededError
from tests.unit.react.conftest import MODEL, erroring_provider


async def test_provider_connection_error_propagates_not_step_budget(price_table):
    provider = erroring_provider(httpx.ConnectError("boom"))
    engine = ReactEngine(provider=provider, tools={}, model=MODEL)
    with pytest.raises(ProxyConnectionError) as exc_info:
        await engine.run("goal", tenant_id="tenant-a", max_steps=3)
    assert not isinstance(exc_info.value, StepBudgetExceededError)


async def test_provider_token_limit_exceeded_propagates(price_table):
    import json

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": MODEL,
                "choices": [{"message": {"role": "assistant", "content": "x"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 1000, "total_tokens": 2000},
            },
        )

    from kernel.provider import LLMProvider

    provider = LLMProvider(
        base_url="http://stub", price_table=price_table, transport=httpx.MockTransport(handler)
    )
    engine = ReactEngine(
        provider=provider,
        tools={},
        model=MODEL,
        max_step_limits=Limits(max_total_tokens=100),
    )
    with pytest.raises(TokenLimitExceededError):
        await engine.run("goal", tenant_id="tenant-a", max_steps=3)
