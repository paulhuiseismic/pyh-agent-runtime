import asyncio
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from kernel.memory import SqliteMemory
from kernel.memory.long_term import LongTermMemory
from kernel.tool import ToolRegistry
from platform_service.agent_service import AgentService
from platform_service.audit import AuditEntry
from platform_service.errors import QuotaExceededError
from platform_service.models import AgentRunRequest
from tests.unit.platform_service.conftest import (
    broken_audit_store,
    erroring_provider,
    platform_config_with_quota,
    slow_stub_provider,
    stub_provider,
)


@pytest.fixture
def db_paths():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield (
            str(Path(tmpdir) / "session.db"),
            str(Path(tmpdir) / "long_term.db"),
        )


async def _build_service(platform_config, db_paths, provider=None, audit_store=None):
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
        audit_store=audit_store,
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


async def test_handle_records_success_audit_entry(platform_config, db_paths, audit_store):
    async for service in _build_service(platform_config, db_paths, audit_store=audit_store):
        await service.handle(AgentRunRequest(goal="1+1?"), tenant_id="tenant-a", source="rest")

    now = datetime.now(timezone.utc)
    summary = await audit_store.query_usage(
        "tenant-a", now - timedelta(minutes=1), now + timedelta(minutes=1)
    )
    assert summary.request_count == 1
    assert summary.total_cost_usd > 0


async def test_handle_records_failure_audit_entry_and_still_raises(
    platform_config, db_paths, audit_store
):
    async for failing_service in _build_service(
        platform_config,
        db_paths,
        provider=erroring_provider(RuntimeError("boom")),
        audit_store=audit_store,
    ):
        with pytest.raises(RuntimeError):
            await failing_service.handle(
                AgentRunRequest(goal="1+1?"), tenant_id="tenant-a", source="cli"
            )

    now = datetime.now(timezone.utc)
    summary = await audit_store.query_usage(
        "tenant-a", now - timedelta(minutes=1), now + timedelta(minutes=1)
    )
    assert summary.request_count == 1


async def test_handle_without_audit_store_behaves_as_before(service):
    # audit_store 默认 None——007-009 既有构造方式不受影响（向后兼容）
    result = await service.handle(AgentRunRequest(goal="1+1?"), tenant_id="tenant-a")
    assert result.status == "success"


async def test_handle_with_broken_audit_store_still_returns_result(
    platform_config, db_paths, caplog
):
    store = broken_audit_store()
    async for service in _build_service(platform_config, db_paths, audit_store=store):
        with caplog.at_level("WARNING"):
            result = await service.handle(AgentRunRequest(goal="1+1?"), tenant_id="tenant-a")
    assert result.status == "success"
    assert any("audit record write failed" in r.message for r in caplog.records)


async def test_quota_exceeded_blocks_kernel_call(platform_config, db_paths, audit_store):
    quota_config = platform_config_with_quota(platform_config, "tenant-a", 0.0001)
    now = datetime.now(timezone.utc)

    await audit_store.record(
        AuditEntry(
            tenant_id="tenant-a",
            source="rest",
            timestamp=now,
            input_tokens=100,
            output_tokens=100,
            cost_usd=1.0,
            status="success",
        )
    )

    class _RefusingProvider:
        async def complete(self, request):
            raise AssertionError("provider.complete() 不应在配额超限时被调用")

    async for service in _build_service(
        quota_config, db_paths, provider=_RefusingProvider(), audit_store=audit_store
    ):
        with pytest.raises(QuotaExceededError):
            await service.handle(AgentRunRequest(goal="1+1?"), tenant_id="tenant-a")


async def test_quota_unaffected_tenant_without_quota(platform_config, db_paths, audit_store):
    async for service in _build_service(platform_config, db_paths, audit_store=audit_store):
        result = await service.handle(AgentRunRequest(goal="1+1?"), tenant_id="tenant-b")
    assert result.status == "success"


async def test_quota_resets_after_window(platform_config, db_paths, audit_store):
    quota_config = platform_config_with_quota(platform_config, "tenant-a", 0.5)
    yesterday = datetime.now(timezone.utc) - timedelta(days=1, hours=1)

    await audit_store.record(
        AuditEntry(
            tenant_id="tenant-a",
            source="rest",
            timestamp=yesterday,
            input_tokens=1000,
            output_tokens=1000,
            cost_usd=100.0,
            status="success",
        )
    )

    async for service in _build_service(quota_config, db_paths, audit_store=audit_store):
        result = await service.handle(AgentRunRequest(goal="1+1?"), tenant_id="tenant-a")
    assert result.status == "success"


async def test_quota_check_serializes_concurrent_requests(platform_config, db_paths, audit_store):
    """`/speckit-analyze` F1 回归测试：并发请求不应同时通过配额检查。"""
    # stub_provider 每次响应 prompt_tokens=5/completion_tokens=5，按
    # conftest 的单价表（input 0.01/output 0.03 每千 token）单次调用
    # 成本为 5/1000*0.01 + 5/1000*0.03 = 0.0002；配额设为低于单次成本，
    # 使得第一个请求执行后累计成本已达到/超过配额，第二个请求的检查
    # 必须被拒绝（而不是两个都在累计成本为 0 时同时通过检查）。
    quota_config = platform_config_with_quota(platform_config, "tenant-a", 0.00015)
    provider = slow_stub_provider(0.05, answer="ok")

    async for service in _build_service(quota_config, db_paths, provider=provider, audit_store=audit_store):
        results = await asyncio.gather(
            service.handle(AgentRunRequest(goal="q1"), tenant_id="tenant-a"),
            service.handle(AgentRunRequest(goal="q2"), tenant_id="tenant-a"),
            return_exceptions=True,
        )

    successes = [r for r in results if not isinstance(r, Exception)]
    quota_errors = [r for r in results if isinstance(r, QuotaExceededError)]
    assert len(successes) == 1
    assert len(quota_errors) == 1


async def test_quota_check_matches_query_endpoint_totals(platform_config, db_paths, audit_store):
    """`/speckit-analyze` F2 回归测试：配额检查与查询端点共享同一份数据。"""
    now = datetime.now(timezone.utc)
    window_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    await audit_store.record(
        AuditEntry(
            tenant_id="tenant-a",
            source="rest",
            timestamp=now,
            input_tokens=10,
            output_tokens=10,
            cost_usd=0.005,
            status="success",
        )
    )

    quota_total = await audit_store.sum_cost_since("tenant-a", window_start)
    query_total = (
        await audit_store.query_usage("tenant-a", window_start, now + timedelta(minutes=1))
    ).total_cost_usd
    assert quota_total == query_total
