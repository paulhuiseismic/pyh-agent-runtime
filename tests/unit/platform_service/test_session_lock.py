import asyncio
import tempfile
from pathlib import Path

import pytest

from kernel.memory import SqliteMemory
from kernel.memory.long_term import LongTermMemory
from kernel.tool import ToolRegistry
from platform_service.agent_service import AgentService
from platform_service.models import AgentRunRequest
from tests.unit.platform_service.conftest import slow_stub_provider


@pytest.fixture
def db_paths():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield (
            str(Path(tmpdir) / "session.db"),
            str(Path(tmpdir) / "long_term.db"),
        )


async def _build_service(platform_config, db_paths, provider):
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


async def test_same_session_concurrent_requests_do_not_corrupt_history(
    platform_config, db_paths
):
    provider = slow_stub_provider(0.2, answer="answer")
    async for service in _build_service(platform_config, db_paths, provider):
        await asyncio.gather(
            service.handle(
                AgentRunRequest(goal="q1", session_id="conv-1"), tenant_id="tenant-a"
            ),
            service.handle(
                AgentRunRequest(goal="q2", session_id="conv-1"), tenant_id="tenant-a"
            ),
        )
        history = await service._session_memory.load("conv-1", tenant_id="tenant-a")
        assert len(history) == 4
        user_messages = [m.content for m in history if m.role == "user"]
        assert sorted(user_messages) == ["q1", "q2"]


async def test_different_sessions_do_not_block_each_other(platform_config, db_paths):
    provider = slow_stub_provider(0.3, answer="answer")
    async for service in _build_service(platform_config, db_paths, provider):
        start = asyncio.get_event_loop().time()
        await asyncio.gather(
            service.handle(
                AgentRunRequest(goal="q1", session_id="conv-a"), tenant_id="tenant-a"
            ),
            service.handle(
                AgentRunRequest(goal="q2", session_id="conv-b"), tenant_id="tenant-a"
            ),
        )
        elapsed = asyncio.get_event_loop().time() - start
        # 每次 handle() 内部有两次顺序的 provider 调用（ReAct 运行 + 长期记忆
        # 提炼），单个 session 自身耗时约为 2*delay；若跨 session 被错误地
        # 串行化，总耗时会再翻倍（约 4*delay）。用中间阈值区分两种情况。
        assert elapsed < 0.3 * 3
