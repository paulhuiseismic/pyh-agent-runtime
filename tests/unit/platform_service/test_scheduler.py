import pytest

from platform_service.errors import ConcurrencyLimitExceededError
from platform_service.scheduler import ConcurrencyScheduler


async def test_tenant_limit_exceeded(platform_config):
    scheduler = ConcurrencyScheduler(platform_config)
    await scheduler.try_acquire("tenant-a")
    await scheduler.try_acquire("tenant-a")  # tenant-a limit is 2
    with pytest.raises(ConcurrencyLimitExceededError) as exc_info:
        await scheduler.try_acquire("tenant-a")
    assert exc_info.value.scope == "tenant"


async def test_global_limit_exceeded(platform_config):
    scheduler = ConcurrencyScheduler(platform_config)
    # global_max_concurrent_requests fixture value is 10; drain it via both tenants
    for _ in range(2):
        await scheduler.try_acquire("tenant-a")
    for _ in range(2):
        await scheduler.try_acquire("tenant-b")
    # bump the global counter directly to simulate other tenants being busy
    scheduler._global_count = platform_config.global_max_concurrent_requests
    with pytest.raises(ConcurrencyLimitExceededError) as exc_info:
        await scheduler.try_acquire("tenant-a")
    assert exc_info.value.scope == "global"


async def test_tenant_a_limit_does_not_affect_tenant_b(platform_config):
    scheduler = ConcurrencyScheduler(platform_config)
    await scheduler.try_acquire("tenant-a")
    await scheduler.try_acquire("tenant-a")
    with pytest.raises(ConcurrencyLimitExceededError):
        await scheduler.try_acquire("tenant-a")

    # tenant-b is unaffected
    await scheduler.try_acquire("tenant-b")


async def test_release_allows_reacquire(platform_config):
    scheduler = ConcurrencyScheduler(platform_config)
    await scheduler.try_acquire("tenant-a")
    await scheduler.try_acquire("tenant-a")
    scheduler.release("tenant-a")
    await scheduler.try_acquire("tenant-a")
