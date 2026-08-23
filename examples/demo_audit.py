"""T024: 多租户强化与审计演示——正常调用产生审计记录 → 查询汇总 →
配额耗尽后新请求被拒绝。

运行: python examples/demo_audit.py（无需网络、无需真实模型密钥；
provider 替换为 stub，配置结构与 examples/platform_config.example.json
一致）
预期输出见 specs/010-multitenant-audit/quickstart.md。
"""

import asyncio
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from kernel.memory import SqliteMemory
from kernel.memory.long_term import LongTermMemory
from kernel.provider import LLMProvider, ModelPrice, PriceTable
from kernel.tool import ToolRegistry
from platform_service.agent_service import AgentService
from platform_service.audit import AuditStore
from platform_service.config import PlatformConfig, TenantConfig
from platform_service.errors import QuotaExceededError
from platform_service.models import AgentRunRequest

MODEL = "azure-gpt4o-mini"
TENANT_ID = "tenant-demo"


def _proxy_payload(content: str) -> dict:
    return {
        "model": MODEL,
        "choices": [
            {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
    }


def stub_provider() -> LLMProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        content = json.dumps({"action": "final_answer", "content": "长沙今天适合穿薄外套。"})
        return httpx.Response(200, json=_proxy_payload(content))

    return LLMProvider(
        base_url="http://stub",
        price_table=PriceTable(prices={MODEL: ModelPrice(0.00015, 0.0006)}),
        transport=httpx.MockTransport(handler),
    )


def build_demo_config(quota_usd: float | None = None) -> PlatformConfig:
    return PlatformConfig(
        tenants=[
            TenantConfig(
                api_key="demo-key",
                tenant_id=TENANT_ID,
                max_concurrent_requests=5,
                daily_cost_quota_usd=quota_usd,
            ),
        ],
        global_max_concurrent_requests=10,
        request_timeout_seconds=10.0,
        model=MODEL,
        max_steps=6,
        provider_base_url="http://stub",
        price_table=PriceTable(prices={MODEL: ModelPrice(0.00015, 0.0006)}),
    )


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_db_path = str(Path(tmpdir) / "audit.db")

        print("=== 1. 成功调用产生审计记录 ===")
        provider = stub_provider()
        session_memory = SqliteMemory(db_path=":memory:", provider=provider, model=MODEL)
        long_term_memory = LongTermMemory(db_path=":memory:", provider=provider, model=MODEL)
        audit_store = AuditStore(audit_db_path)
        service = AgentService(
            provider=provider,
            tool_registry=ToolRegistry(),
            session_memory=session_memory,
            long_term_memory=long_term_memory,
            config=build_demo_config(),
            audit_store=audit_store,
        )
        result = await service.handle(
            AgentRunRequest(goal="长沙今天穿什么合适？"), tenant_id=TENANT_ID, source="rest"
        )
        print(f"结果: {result.answer}")
        await session_memory.aclose()
        await long_term_memory.aclose()

        print("\n=== 2. 查询用量汇总 ===")
        now = datetime.now(timezone.utc)
        summary = await audit_store.query_usage(
            TENANT_ID, now - timedelta(minutes=1), now + timedelta(minutes=1)
        )
        print(
            f"请求数: {summary.request_count}, 输入 token: "
            f"{summary.total_input_tokens}, 输出 token: "
            f"{summary.total_output_tokens}, 总成本: {summary.total_cost_usd} USD"
        )
        await audit_store.aclose()

        print("\n=== 3. 配额耗尽后新请求被拒绝 ===")
        # 配额设为单次调用成本的一半，使第一次调用后即耗尽配额
        quota_config = build_demo_config(quota_usd=summary.total_cost_usd / 2)
        audit_store2 = AuditStore(audit_db_path)
        provider2 = stub_provider()
        session_memory2 = SqliteMemory(db_path=":memory:", provider=provider2, model=MODEL)
        long_term_memory2 = LongTermMemory(db_path=":memory:", provider=provider2, model=MODEL)
        service2 = AgentService(
            provider=provider2,
            tool_registry=ToolRegistry(),
            session_memory=session_memory2,
            long_term_memory=long_term_memory2,
            config=quota_config,
            audit_store=audit_store2,
        )
        try:
            await service2.handle(
                AgentRunRequest(goal="再问一次"), tenant_id=TENANT_ID, source="rest"
            )
            print("未预期：请求未被拒绝")
        except QuotaExceededError as exc:
            print(f"请求被拒绝: {exc}")
        await session_memory2.aclose()
        await long_term_memory2.aclose()
        await audit_store2.aclose()

    print(
        "\n演示完成：审计记录、用量查询、配额强化三项能力均按预期工作，"
        "配额检查与查询汇总共享同一份 AuditStore 数据（FR-008/SC-007）。"
    )


if __name__ == "__main__":
    asyncio.run(main())
