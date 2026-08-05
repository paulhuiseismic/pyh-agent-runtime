import pytest

from platform_service.auth import resolve_tenant
from platform_service.errors import AuthenticationError


def test_resolve_tenant_success(platform_config):
    tenant_id = resolve_tenant("key-a", platform_config)
    assert tenant_id == "tenant-a"


def test_resolve_tenant_unmatched_key_raises(platform_config):
    with pytest.raises(AuthenticationError):
        resolve_tenant("no-such-key", platform_config)


def test_resolve_tenant_missing_key_raises(platform_config):
    with pytest.raises(AuthenticationError):
        resolve_tenant(None, platform_config)
