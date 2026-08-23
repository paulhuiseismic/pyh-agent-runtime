import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from kernel.memory import SqliteMemory
from kernel.memory.long_term import LongTermMemory
from kernel.tool import ToolRegistry
from platform_service.agent_service import AgentService
from platform_service.app import create_app
from platform_service.audit import AuditEntry
from tests.unit.platform_service.conftest import stub_provider


async def _build_app(platform_config, audit_store, provider=None):
    provider = provider or stub_provider("42")
    with tempfile.TemporaryDirectory() as tmpdir:
        session_memory = SqliteMemory(
            db_path=str(Path(tmpdir) / "session.db"), provider=provider, model=platform_config.model
        )
        long_term_memory = LongTermMemory(
            db_path=str(Path(tmpdir) / "long_term.db"), provider=provider, model=platform_config.model
        )
        try:
            service = AgentService(
                provider=provider,
                tool_registry=ToolRegistry(),
                session_memory=session_memory,
                long_term_memory=long_term_memory,
                config=platform_config,
                audit_store=audit_store,
            )
            yield create_app(platform_config, agent_service=service)
        finally:
            await session_memory.aclose()
            await long_term_memory.aclose()


async def test_query_usage_returns_matching_summary(platform_config, audit_store):
    now = datetime.now(timezone.utc)
    await audit_store.record(
        AuditEntry(
            tenant_id="tenant-a",
            source="rest",
            timestamp=now,
            input_tokens=10,
            output_tokens=5,
            cost_usd=0.002,
            status="success",
        )
    )

    async for app in _build_app(platform_config, audit_store):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/v1/audit/usage",
                headers={"X-API-Key": "key-a"},
                params={
                    "start": (now - timedelta(minutes=1)).isoformat(),
                    "end": (now + timedelta(minutes=1)).isoformat(),
                },
            )
        assert response.status_code == 200
        body = response.json()
        assert body["tenant_id"] == "tenant-a"
        assert body["request_count"] == 1
        assert body["total_input_tokens"] == 10
        assert body["total_output_tokens"] == 5
        assert abs(body["total_cost_usd"] - 0.002) < 1e-9


async def test_query_usage_empty_range_returns_zero_summary(platform_config, audit_store):
    now = datetime.now(timezone.utc)
    async for app in _build_app(platform_config, audit_store):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/v1/audit/usage",
                headers={"X-API-Key": "key-a"},
                params={
                    "start": (now - timedelta(days=1)).isoformat(),
                    "end": now.isoformat(),
                },
            )
        assert response.status_code == 200
        body = response.json()
        assert body["request_count"] == 0
        assert body["total_cost_usd"] == 0


async def test_query_usage_missing_api_key_returns_401(platform_config, audit_store):
    async for app in _build_app(platform_config, audit_store):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/v1/audit/usage")
        assert response.status_code == 401


async def test_query_usage_bad_api_key_returns_401(platform_config, audit_store):
    async for app in _build_app(platform_config, audit_store):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/v1/audit/usage", headers={"X-API-Key": "not-a-real-key"}
            )
        assert response.status_code == 401


async def test_query_usage_malformed_start_returns_422(platform_config, audit_store):
    async for app in _build_app(platform_config, audit_store):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/v1/audit/usage",
                headers={"X-API-Key": "key-a"},
                params={"start": "not-a-date"},
            )
        assert response.status_code == 422


async def test_query_usage_tenant_isolation(platform_config, audit_store):
    now = datetime.now(timezone.utc)
    await audit_store.record(
        AuditEntry(
            tenant_id="tenant-a",
            source="rest",
            timestamp=now,
            input_tokens=1,
            output_tokens=1,
            cost_usd=0.001,
            status="success",
        )
    )
    await audit_store.record(
        AuditEntry(
            tenant_id="tenant-b",
            source="rest",
            timestamp=now,
            input_tokens=100,
            output_tokens=100,
            cost_usd=100.0,
            status="success",
        )
    )

    async for app in _build_app(platform_config, audit_store):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/v1/audit/usage",
                headers={"X-API-Key": "key-a"},
                params={
                    "start": (now - timedelta(minutes=1)).isoformat(),
                    "end": (now + timedelta(minutes=1)).isoformat(),
                },
            )
        body = response.json()
        assert body["tenant_id"] == "tenant-a"
        assert body["total_cost_usd"] == 0.001


async def test_agent_run_quota_exceeded_returns_402(platform_config, audit_store):
    import dataclasses

    quota_config = dataclasses.replace(
        platform_config,
        tenants=[
            dataclasses.replace(t, daily_cost_quota_usd=0.0001) if t.tenant_id == "tenant-a" else t
            for t in platform_config.tenants
        ],
    )
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

    async for app in _build_app(quota_config, audit_store):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v1/agent/run",
                headers={"X-API-Key": "key-a"},
                json={"goal": "1+1?"},
            )
        assert response.status_code == 402
