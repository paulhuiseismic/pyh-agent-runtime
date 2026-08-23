# Quickstart: 多租户强化与审计

## 前置条件

- 已完成 007（REST）/008（CLI）/009（消息网关）。
- 一份平台配置文件，新增 `audit_db_path`（可选，默认
  `platform_audit.db`）与至少一个租户的 `daily_cost_quota_usd`
  （可选），结构见
  [examples/platform_config.example.json](../../examples/platform_config.example.json)。

## 1. 正常调用产生审计记录

```powershell
$env:PLATFORM_SERVICE_API_KEY = "demo-key"
$env:PLATFORM_SERVICE_CONFIG = "path/to/config.json"
pyh-agent "1+1等于几？"
```

**预期**：命令正常返回结果；`platform_audit.db` 中新增一条
`tenant_id=tenant-demo, source="cli", status="success"` 的记录（可用
`sqlite3 platform_audit.db "select * from audit_entries"` 直接查看）。

## 2. 查询用量汇总

```powershell
# 需先按 007 quickstart 启动 uvicorn platform_service.app:app
curl http://localhost:8000/v1/audit/usage -H "X-API-Key: demo-key"
```

**预期输出**：`{"tenant_id": "tenant-demo", "request_count": 1,
"total_input_tokens": ..., "total_output_tokens": ...,
"total_cost_usd": ..., ...}`，与步骤 1 产生的记录一致。

## 3. 配额耗尽后请求被拒绝

为某租户配置一个很小的 `daily_cost_quota_usd`（如 `0.0001`），重复
步骤 1 的调用直到累计成本达到该配额，再发起一次新请求：

| 场景 | 预期 |
|------|------|
| REST（`/v1/agent/run`） | `402`（配额超限） |
| CLI | `EXIT_QUOTA_EXCEEDED` 退出码，见 `platform_service/cli.py` 常量定义 |
| 消息网关出站回调 | `status="quota_exceeded"` |

未配置配额的其他租户不受影响（SC-006）。

## 4. 无网络验证（stub provider，供自动化测试/CI 使用）

```powershell
.venv\Scripts\python examples\demo_audit.py
.venv\Scripts\python -m pytest tests/unit/platform_service/test_audit.py tests/unit/platform_service/test_app_audit.py -v
```

**预期输出**：demo 脚本依次打印"成功调用产生审计记录"→"查询汇总"→
"配额耗尽后被拒绝"三个阶段的结果；pytest 全绿。

## 5. 持久化验证（SC-003）

```powershell
.venv\Scripts\python -c "
import asyncio
from platform_service.audit import AuditStore, AuditEntry
from datetime import datetime, timezone

async def main():
    store = AuditStore('quickstart_audit.db')
    await store.record(AuditEntry(
        tenant_id='t1', source='cli', timestamp=datetime.now(timezone.utc),
        input_tokens=10, output_tokens=5, cost_usd=0.001, status='success'))
    await store.aclose()

    # 模拟进程重启：用新连接指向同一文件
    store2 = AuditStore('quickstart_audit.db')
    summary = await store2.query_usage(
        't1', datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0),
        datetime.now(timezone.utc))
    print(summary)
    await store2.aclose()

asyncio.run(main())
"
```

**预期输出**：`UsageSummary(..., request_count=1, ...)`——新连接仍能
读到此前连接写入的记录。
