import asyncio
import tempfile
from pathlib import Path

import httpx
import pytest

from kernel.memory import SqliteMemory
from kernel.memory.long_term import LongTermMemory
from kernel.tool import ToolRegistry
from platform_service.agent_service import AgentService
from platform_service.app import create_app
from platform_service.config import PlatformConfig, TenantConfig
from tests.unit.platform_service.conftest import MODEL, slow_stub_provider


@pytest.fixture
def db_paths():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield (
            str(Path(tmpdir) / "session.db"),
            str(Path(tmpdir) / "long_term.db"),
        )


async def _build_app(config, db_paths, provider):
    session_memory = SqliteMemory(db_path=db_paths[0], provider=provider, model=config.model)
    long_term_memory = LongTermMemory(
        db_path=db_paths[1], provider=provider, model=config.model
    )
    service = AgentService(
        provider=provider,
        tool_registry=ToolRegistry(),
        session_memory=session_memory,
        long_term_memory=long_term_memory,
        config=config,
    )
    try:
        yield create_app(config, agent_service=service)
    finally:
        await session_memory.aclose()
        await long_term_memory.aclose()


async def test_second_concurrent_request_gets_429(db_paths):
    from kernel.provider import ModelPrice, PriceTable

    config = PlatformConfig(
        tenants=[TenantConfig(api_key="key-a", tenant_id="tenant-a", max_concurrent_requests=1)],
        global_max_concurrent_requests=10,
        request_timeout_seconds=5.0,
        model=MODEL,
        max_steps=5,
        provider_base_url="http://stub",
        price_table=PriceTable(prices={MODEL: ModelPrice(0.01, 0.03)}),
    )
    provider = slow_stub_provider(0.5)
    async for app in _build_app(config, db_paths, provider):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            first = asyncio.create_task(
                client.post(
                    "/v1/agent/run", headers={"X-API-Key": "key-a"}, json={"goal": "q1"}
                )
            )
            await asyncio.sleep(0.1)  # let the first request acquire the slot
            second = await client.post(
                "/v1/agent/run", headers={"X-API-Key": "key-a"}, json={"goal": "q2"}
            )
            assert second.status_code == 429

            first_response = await first
            assert first_response.status_code == 200


async def test_slow_request_returns_504(db_paths):
    from kernel.provider import ModelPrice, PriceTable

    config = PlatformConfig(
        tenants=[TenantConfig(api_key="key-a", tenant_id="tenant-a", max_concurrent_requests=2)],
        global_max_concurrent_requests=10,
        request_timeout_seconds=0.2,
        model=MODEL,
        max_steps=5,
        provider_base_url="http://stub",
        price_table=PriceTable(prices={MODEL: ModelPrice(0.01, 0.03)}),
    )
    provider = slow_stub_provider(5.0)
    async for app in _build_app(config, db_paths, provider):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v1/agent/run", headers={"X-API-Key": "key-a"}, json={"goal": "q1"}
            )
        assert response.status_code == 504
