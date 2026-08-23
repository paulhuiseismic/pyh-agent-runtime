import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from platform_service.audit import AuditEntry, AuditStore

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"


def _entry(**overrides) -> AuditEntry:
    kwargs = dict(
        tenant_id=TENANT_A,
        source="rest",
        timestamp=datetime.now(timezone.utc),
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.001,
        status="success",
    )
    kwargs.update(overrides)
    return AuditEntry(**kwargs)


async def test_record_and_query_usage_aggregates_correctly(audit_store: AuditStore):
    now = datetime.now(timezone.utc)
    await audit_store.record(_entry(timestamp=now, input_tokens=10, output_tokens=5, cost_usd=0.001))
    await audit_store.record(_entry(timestamp=now, input_tokens=20, output_tokens=8, cost_usd=0.002))

    summary = await audit_store.query_usage(
        TENANT_A, now - timedelta(minutes=1), now + timedelta(minutes=1)
    )
    assert summary.tenant_id == TENANT_A
    assert summary.request_count == 2
    assert summary.total_input_tokens == 30
    assert summary.total_output_tokens == 13
    assert abs(summary.total_cost_usd - 0.003) < 1e-9


async def test_query_usage_empty_range_returns_zero_summary(audit_store: AuditStore):
    now = datetime.now(timezone.utc)
    summary = await audit_store.query_usage(TENANT_A, now - timedelta(days=1), now)
    assert summary.request_count == 0
    assert summary.total_input_tokens == 0
    assert summary.total_output_tokens == 0
    assert summary.total_cost_usd == 0


async def test_sum_cost_since_excludes_entries_outside_window(audit_store: AuditStore):
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1, hours=1)
    await audit_store.record(_entry(timestamp=yesterday, cost_usd=100.0))
    await audit_store.record(_entry(timestamp=now, cost_usd=0.5))

    window_start = now - timedelta(hours=1)
    total = await audit_store.sum_cost_since(TENANT_A, window_start)
    assert abs(total - 0.5) < 1e-9


async def test_records_persist_across_new_connection_to_same_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "audit.db")
        now = datetime.now(timezone.utc)

        store1 = AuditStore(db_path)
        await store1.record(_entry(timestamp=now))
        await store1.aclose()

        store2 = AuditStore(db_path)
        summary = await store2.query_usage(
            TENANT_A, now - timedelta(minutes=1), now + timedelta(minutes=1)
        )
        assert summary.request_count == 1
        await store2.aclose()


async def test_query_usage_tenant_isolation(audit_store: AuditStore):
    now = datetime.now(timezone.utc)
    await audit_store.record(_entry(tenant_id=TENANT_A, timestamp=now, cost_usd=1.0))
    await audit_store.record(_entry(tenant_id=TENANT_B, timestamp=now, cost_usd=2.0))

    summary_a = await audit_store.query_usage(
        TENANT_A, now - timedelta(minutes=1), now + timedelta(minutes=1)
    )
    assert summary_a.request_count == 1
    assert summary_a.total_cost_usd == 1.0
