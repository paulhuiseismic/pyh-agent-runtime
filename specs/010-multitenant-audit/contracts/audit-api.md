# Contract: 用量审计查询 API + `AgentService` 扩展契约

**Consumer**: 已通过 007 静态 API Key 识别的租户自身（查询自己的用量）
**Provider**: `platform_service`（在 007/008/009 已建立的三个入口之上
组装）

数据结构见 [data-model.md](../data-model.md)。

## 查询接口

### `GET /v1/audit/usage`

**请求头**：`X-API-Key: <该租户的 API Key>`（复用 007 `resolve_tenant`）

**查询参数**（均可选）：

| 参数 | 格式 | 缺省值 |
|------|------|--------|
| `start` | ISO8601 | 当日 UTC 零点 |
| `end` | ISO8601 | 当前时间 |

不接受 `tenant_id` 参数——查询范围永远限定为调用方自身租户
（research.md R5，FR-005）。

**响应**：

| 场景 | HTTP 状态码 | 响应体要点 |
|------|------------|-----------|
| 成功 | 200 | `UsageSummary`（`request_count`/`total_input_tokens`/`total_output_tokens`/`total_cost_usd`） |
| 该范围内无记录 | 200 | `UsageSummary`，全部数值字段为 0（US2 验收场景 2） |
| 身份识别失败 | 401 | 错误类型标识 + 可读原因（复用 007 既有行为） |
| `start`/`end` 格式非法 | 422 | 参数校验错误详情 |

## `/v1/agent/run` 端点新增的失败分支

| 场景 | HTTP 状态码 | 说明 |
|------|------------|------|
| 该租户当日累计成本已达配额上限（`QuotaExceededError`） | 402 | 与既有 429（并发超限）/502（内核失败）/504（超时）并列，彼此可区分 |

CLI（008）新增 `EXIT_QUOTA_EXCEEDED`（数值见 tasks.md 实现时在
`contracts/cli-contract.md` 之外单独追加，不重排 008 已发布的既有
数值）；消息网关（009）出站回调新增 `status="quota_exceeded"`
（沿用既有 `status`/`error` 字段结构，不新增字段）。

## `AgentService` 内部契约扩展

```python
from platform_service import AgentService, AgentRunRequest
from platform_service.audit import AuditStore

service = AgentService(
    provider=...,
    tool_registry=...,
    session_memory=...,
    long_term_memory=...,
    config=...,
    audit_store=AuditStore("platform_audit.db"),  # 新增，可选，默认 None
)
result = await service.handle(
    AgentRunRequest(goal="...", session_id="..."),
    tenant_id="...",
    source="rest",  # 新增，可选，默认 "unknown"
)
```

**行为契约**：

1. `audit_store=None`（未提供）时，`handle()` 的行为与 007-009 既有
   版本完全一致——不做配额检查、不写审计记录（向后兼容，research.md
   R2）。
2. `audit_store` 非空且调用方租户配置了 `daily_cost_quota_usd` 时，
   `handle()` MUST 在触发任何 `ReactEngine`/`LLMProvider` 调用之前
   完成配额检查，超限时抛 `QuotaExceededError`（FR-007）。
3. `audit_store` 非空时，`handle()` 的每次调用（无论成功或失败）
   MUST 尝试写入一条对应的 `AuditEntry`；写入失败 MUST NOT 影响
   `handle()` 原有的返回值/异常传播行为（FR-003）。
4. 配额检查使用的累计成本 MUST 直接来自 `audit_store` 已持久化的
   记录，MUST NOT 维护额外的、独立于 `AuditStore` 的用量计数
   （FR-008）。

## 兼容性承诺

- 不修改 001（`LLMProvider`）/002（`ReactEngine`）已冻结的任何公共
  接口。
- `AgentService.__init__`/`handle()` 新增的参数均为带安全默认值的
  可选关键字参数，007-009 已有调用方（包括测试与 demo 脚本）零改动
  即可继续通过。
- `PlatformConfig`/`TenantConfig` 新增字段均有安全默认值，不破坏
  007-009 已有配置文件的向后兼容性。
