import pytest

from kernel.provider.errors import InvalidRequestError
from kernel.provider.models import ModelPrice, PriceTable
from platform_service.config import ChannelConfig, PlatformConfig, TenantConfig
from platform_service.errors import (
    AuthenticationError,
    ChannelNotFoundError,
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
    assert config.channels == []
    assert config.callback_timeout_seconds == 10.0
    assert config.callback_max_retries == 3


@pytest.mark.parametrize(
    "field_name,value",
    [
        ("global_max_concurrent_requests", 0),
        ("request_timeout_seconds", 0),
        ("max_steps", 0),
        ("callback_timeout_seconds", 0),
        ("callback_max_retries", 0),
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


def test_channel_not_found_error_channel_id():
    err = ChannelNotFoundError(channel_id="unknown-channel")
    assert err.channel_id == "unknown-channel"


@pytest.mark.parametrize(
    "field_name",
    ["channel_id", "tenant_id", "callback_url"],
)
def test_channel_config_empty_fields_rejected(field_name):
    kwargs = dict(
        channel_id="c1", tenant_id="t1", callback_url="http://callback.test"
    )
    kwargs[field_name] = ""
    with pytest.raises(InvalidRequestError):
        ChannelConfig(**kwargs)


def test_duplicate_channel_id_rejected():
    channels = [
        ChannelConfig(channel_id="dup", tenant_id="t1", callback_url="http://a.test"),
        ChannelConfig(channel_id="dup", tenant_id="t2", callback_url="http://b.test"),
    ]
    with pytest.raises(InvalidRequestError):
        PlatformConfig(**_base_kwargs(channels=channels))


def test_load_config_from_file_defaults_channels_to_empty(tmp_path):
    import json

    from platform_service.config import load_config_from_file

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "tenants": [
                    {"api_key": "k1", "tenant_id": "t1", "max_concurrent_requests": 1}
                ],
                "global_max_concurrent_requests": 5,
                "request_timeout_seconds": 10.0,
                "model": MODEL,
                "max_steps": 3,
                "provider_base_url": "http://stub",
                "price_table": {
                    MODEL: {"input_per_1k_usd": 0.01, "output_per_1k_usd": 0.03}
                },
            }
        ),
        encoding="utf-8",
    )
    config = load_config_from_file(str(config_path))
    assert config.channels == []
    assert config.callback_timeout_seconds == 10.0
    assert config.callback_max_retries == 3
