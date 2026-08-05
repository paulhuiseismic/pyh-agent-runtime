from platform_service.config import PlatformConfig
from platform_service.errors import AuthenticationError


def resolve_tenant(api_key: str | None, config: PlatformConfig) -> str:
    if api_key:
        for tenant in config.tenants:
            if tenant.api_key == api_key:
                return tenant.tenant_id
    raise AuthenticationError("no tenant matches the provided API key")
