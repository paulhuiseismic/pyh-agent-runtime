import asyncio

from platform_service.config import PlatformConfig
from platform_service.errors import ConcurrencyLimitExceededError


class ConcurrencyScheduler:
    """per-tenant + 全局并发计数器，超限立即拒绝，不排队（research.md R2，FR-012）。"""

    def __init__(self, config: PlatformConfig) -> None:
        self._config = config
        self._limits = {t.tenant_id: t.max_concurrent_requests for t in config.tenants}
        self._counts: dict[str, int] = {t.tenant_id: 0 for t in config.tenants}
        self._global_count = 0
        self._lock = asyncio.Lock()

    async def try_acquire(self, tenant_id: str) -> None:
        async with self._lock:
            if self._global_count >= self._config.global_max_concurrent_requests:
                raise ConcurrencyLimitExceededError(scope="global")
            tenant_limit = self._limits.get(tenant_id)
            tenant_count = self._counts.get(tenant_id, 0)
            if tenant_limit is not None and tenant_count >= tenant_limit:
                raise ConcurrencyLimitExceededError(scope="tenant")

            self._global_count += 1
            self._counts[tenant_id] = tenant_count + 1

    def release(self, tenant_id: str) -> None:
        if self._global_count > 0:
            self._global_count -= 1
        if self._counts.get(tenant_id, 0) > 0:
            self._counts[tenant_id] -= 1
