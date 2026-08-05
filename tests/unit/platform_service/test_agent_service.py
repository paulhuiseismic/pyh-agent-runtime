import tempfile
from pathlib import Path

import pytest

from kernel.memory import SqliteMemory
from kernel.memory.long_term import LongTermMemory
from kernel.tool import ToolRegistry
from platform_service.agent_service import AgentService
from platform_service.models import AgentRunRequest
from tests.unit.platform_service.conftest import erroring_provider, stub_provider


@pytest.fixture
def db_paths():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield (
            str(Path(tmpdir) / "session.db"),
            str(Path(tmpdir) / "long_term.db"),
        )


async def _build_service(platform_config, db_paths, provider=None):
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
        yield service
    finally:
        await session_memory.aclose()
        await long_term_memory.aclose()


@pytest.fixture
async def service(platform_config, db_paths):
    async for s in _build_service(platform_config, db_paths):
        yield s


async def test_handle_returns_success_result(service):
    result = await service.handle(AgentRunRequest(goal="1+1?"), tenant_id="tenant-a")
    assert result.status == "success"
    assert result.answer == "hello world"


async def test_handle_with_session_id_persists_history(service):
    result = await service.handle(
        AgentRunRequest(goal="1+1?", session_id="conv-1"), tenant_id="tenant-a"
    )
    assert result.session_id == "conv-1"

    history = await service._session_memory.load("conv-1", tenant_id="tenant-a")
    assert [m.content for m in history] == ["1+1?", "hello world"]
    assert [m.role for m in history] == ["user", "assistant"]


async def test_handle_propagates_provider_error(platform_config, db_paths):
    async for failing_service in _build_service(
        platform_config, db_paths, provider=erroring_provider(RuntimeError("boom"))
    ):
        with pytest.raises(Exception):
            await failing_service.handle(AgentRunRequest(goal="1+1?"), tenant_id="tenant-a")
