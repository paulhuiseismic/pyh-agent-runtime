"""T007: models 校验单元测试。"""

import pytest

from kernel.provider.errors import InvalidRequestError
from kernel.provider.models import (
    DEFAULT_MAX_COST_USD,
    DEFAULT_MAX_TOTAL_TOKENS,
    DEFAULT_TIMEOUT_SECONDS,
    Limits,
    LLMRequest,
    Message,
    ModelPrice,
    PriceTable,
)


def make_request(**overrides) -> LLMRequest:
    kwargs = dict(
        tenant_id="tenant-a",
        model="gpt-test",
        messages=(Message(role="user", content="hi"),),
    )
    kwargs.update(overrides)
    return LLMRequest(**kwargs)


class TestMessage:
    def test_valid_roles(self):
        for role in ("system", "user", "assistant", "tool"):
            assert Message(role=role, content="x").role == role

    def test_invalid_role_rejected(self):
        with pytest.raises(InvalidRequestError):
            Message(role="robot", content="x")

    def test_empty_content_rejected(self):
        with pytest.raises(InvalidRequestError):
            Message(role="user", content="")


class TestLimits:
    def test_safe_defaults(self):
        limits = Limits()
        assert limits.timeout_seconds == DEFAULT_TIMEOUT_SECONDS
        assert limits.max_total_tokens == DEFAULT_MAX_TOTAL_TOKENS
        assert limits.max_cost_usd == DEFAULT_MAX_COST_USD

    @pytest.mark.parametrize("field,value", [
        ("timeout_seconds", 0),
        ("timeout_seconds", -1),
        ("timeout_seconds", float("nan")),
        ("timeout_seconds", float("inf")),
        ("max_total_tokens", 0),
        ("max_total_tokens", -100),
        ("max_cost_usd", 0),
        ("max_cost_usd", float("inf")),
    ])
    def test_no_unlimited_or_invalid_values(self, field, value):
        with pytest.raises(InvalidRequestError):
            Limits(**{field: value})

    def test_non_integer_token_limit_rejected(self):
        with pytest.raises(InvalidRequestError):
            Limits(max_total_tokens=1.5)


class TestLLMRequest:
    def test_valid_request(self):
        req = make_request()
        assert req.tenant_id == "tenant-a"

    @pytest.mark.parametrize("tenant_id", ["", "   ", None])
    def test_missing_tenant_rejected(self, tenant_id):
        with pytest.raises(InvalidRequestError):
            make_request(tenant_id=tenant_id)

    def test_empty_messages_rejected(self):
        with pytest.raises(InvalidRequestError):
            make_request(messages=())

    def test_empty_model_rejected(self):
        with pytest.raises(InvalidRequestError):
            make_request(model="")

    @pytest.mark.parametrize("temperature", [-0.1, 2.1])
    def test_temperature_out_of_range_rejected(self, temperature):
        with pytest.raises(InvalidRequestError):
            make_request(temperature=temperature)


class TestPriceTable:
    def test_price_lookup(self):
        table = PriceTable(prices={"m": ModelPrice(0.01, 0.03)})
        assert table.price_for("m").output_per_1k_usd == 0.03

    def test_unknown_model_rejected(self):
        with pytest.raises(InvalidRequestError):
            PriceTable().price_for("unknown")

    def test_negative_price_rejected(self):
        with pytest.raises(InvalidRequestError):
            ModelPrice(-0.01, 0.03)
