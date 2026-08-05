import pytest

from kernel.provider.errors import InvalidRequestError
from kernel.provider.models import ModelPrice, PriceTable
from platform_service.config import PlatformConfig, TenantConfig
from platform_service.errors import (
    AuthenticationError,
    ConcurrencyLimitExceededError,
    RequestTimeoutError,
)

MODEL = "test-model"


def _price_table() -> PriceTable:
    return PriceTable(prices={MODEL: ModelPrice(input_per_1k_usd=0.01, output_per_1k_usd=0.03)})


def _base_kwargs(**overrides):
    kwargs = dict(
        tenants=[TenantConfig(api_key="k1", tenant_id="t1", max_concurrent_requests=1)],
        global_max_concurrent_requests=5,
        request_timeout_seconds=10.0,
        model=MODEL,
        max_steps=3,
        provider_base_url="http://stub",
        price_table=_price_table(),
    )
    kwargs.update(overrides)
    return kwargs


def test_valid_config_constructs():
    config = PlatformConfig(**_base_kwargs())
    assert config.model == MODEL
    assert config.mcp_servers == []
    assert config.provider_api_key is None


@pytest.mark.parametrize(
    "field_name,value",
    [
        ("global_max_concurrent_requests", 0),
        ("request_timeout_seconds", 0),
        ("max_steps", 0),
    ],
)
def test_non_positive_numeric_fields_rejected(field_name, value):
    with pytest.raises(InvalidRequestError):
        PlatformConfig(**_base_kwargs(**{field_name: value}))


def test_empty_model_rejected():
    with pytest.raises(InvalidRequestError):
        PlatformConfig(**_base_kwargs(model=""))


def test_empty_provider_base_url_rejected():
    with pytest.raises(InvalidRequestError):
        PlatformConfig(**_base_kwargs(provider_base_url=""))


def test_price_table_missing_model_price_rejected():
    empty_price_table = PriceTable(prices={})
    with pytest.raises(InvalidRequestError):
        PlatformConfig(**_base_kwargs(price_table=empty_price_table))


def test_duplicate_api_key_rejected():
    tenants = [
        TenantConfig(api_key="dup", tenant_id="t1", max_concurrent_requests=1),
        TenantConfig(api_key="dup", tenant_id="t2", max_concurrent_requests=1),
    ]
    with pytest.raises(InvalidRequestError):
        PlatformConfig(**_base_kwargs(tenants=tenants))


def test_duplicate_tenant_id_rejected():
    tenants = [
        TenantConfig(api_key="k1", tenant_id="dup", max_concurrent_requests=1),
        TenantConfig(api_key="k2", tenant_id="dup", max_concurrent_requests=1),
    ]
    with pytest.raises(InvalidRequestError):
        PlatformConfig(**_base_kwargs(tenants=tenants))


def test_tenant_config_non_positive_limit_rejected():
    with pytest.raises(InvalidRequestError):
        TenantConfig(api_key="k1", tenant_id="t1", max_concurrent_requests=0)


def test_authentication_error_detail():
    err = AuthenticationError("no matching tenant")
    assert err.detail == "no matching tenant"


def test_concurrency_limit_exceeded_scope():
    err = ConcurrencyLimitExceededError(scope="tenant")
    assert err.scope == "tenant"


def test_request_timeout_error_seconds():
    err = RequestTimeoutError(timeout_seconds=30.0)
    assert err.timeout_seconds == 30.0
