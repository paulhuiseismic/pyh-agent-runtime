import tempfile
from pathlib import Path

import httpx
import pytest

from kernel.memory import SqliteMemory
from kernel.memory.long_term import LongTermMemory
from kernel.tool import ToolRegistry
from platform_service.agent_service import AgentService
from platform_service.app import create_app
from tests.unit.platform_service.conftest import erroring_provider, stub_provider


@pytest.fixture
def db_paths():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield (
            str(Path(tmpdir) / "session.db"),
            str(Path(tmpdir) / "long_term.db"),
        )


async def _build_app(platform_config, db_paths, provider=None):
    provider = provider or stub_provider("hello world")
    session_memory = SqliteMemory(
        db_path=db_paths[0], provider=provider, model=platform_config.model
    )
    long_term_memory = LongTermMemory(
        db_path=db_paths[1], provider=provider, model=platform_config.model
    )
    service = AgentService(
        provider=provider,
        tool_registry=ToolRegistry(),
        session_memory=session_memory,
        long_term_memory=long_term_memory,
        config=platform_config,
    )
    try:
        yield create_app(platform_config, agent_service=service)
    finally:
        await session_memory.aclose()
        await long_term_memory.aclose()


async def test_success_response(platform_config, db_paths):
    async for app in _build_app(platform_config, db_paths):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v1/agent/run",
                headers={"X-API-Key": "key-a"},
                json={"goal": "1+1?"},
            )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        assert body["answer"] == "hello world"


async def test_missing_api_key_returns_401(platform_config, db_paths):
    async for app in _build_app(platform_config, db_paths):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/v1/agent/run", json={"goal": "1+1?"})
        assert response.status_code == 401


async def test_bad_api_key_returns_401(platform_config, db_paths):
    async for app in _build_app(platform_config, db_paths):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v1/agent/run",
                headers={"X-API-Key": "not-a-real-key"},
                json={"goal": "1+1?"},
            )
        assert response.status_code == 401


async def test_missing_goal_returns_422(platform_config, db_paths):
    async for app in _build_app(platform_config, db_paths):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v1/agent/run", headers={"X-API-Key": "key-a"}, json={}
            )
        assert response.status_code == 422


async def test_kernel_failure_returns_502(platform_config, db_paths):
    async for app in _build_app(
        platform_config, db_paths, provider=erroring_provider(RuntimeError("boom"))
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v1/agent/run", headers={"X-API-Key": "key-a"}, json={"goal": "1+1?"}
            )
        assert response.status_code == 502
