# Data Model: 多租户强化与审计

## 复用的既有实体（零改动）

- **`AgentRunRequest`/`AgentRunResult`**：不新增字段，`handle()` 的
  返回值语义不变。
- **`LLMResponse`/`TokenUsage`**（001）：`_UsageTrackingProvider` 读取
  其 `usage`/`cost_usd` 字段，不修改其定义。
- **`platform_request_span`**：零改动复用，各入口自行在其既有的
  `span.set_result(...)` 分支旁新增 `"quota_exceeded"` 这一新取值。

## 新增/扩展的配置实体

### `TenantConfig` 新增字段

| 字段 | 类型 | 默认值 | 校验 |
|------|------|--------|------|
| `daily_cost_quota_usd` | `float \| None` | `None` | 若提供须 `> 0` |

`None` 表示该租户不受本 feature 的配额检查影响（FR-006）。

### `PlatformConfig` 新增字段

| 字段 | 类型 | 默认值 |
|------|------|--------|
| `audit_db_path` | `str` | `"platform_audit.db"` |

## 新增的持久化实体（`audit.py`）

### `AuditEntry`（写入用，dataclass）

| 字段 | 类型 | 说明 |
|------|------|------|
| `tenant_id` | `str` | 所属租户 |
| `source` | `str` | 来源入口：`"rest"` / `"cli"` / `"message_gateway"` / `"unknown"` |
| `timestamp` | `datetime`（UTC） | 请求完成时间 |
| `input_tokens` | `int` | 本次调用累计输入 token |
| `output_tokens` | `int` | 本次调用累计输出 token |
| `cost_usd` | `float` | 本次调用累计成本 |
| `status` | `str` | `"success"` / `"failure"` |

对应 SQLite 表 `audit_entries`（`id` 自增主键 + 上述字段，
`tenant_id`/`timestamp` 建索引以支持按租户+时间范围查询）。

### `UsageSummary`（查询结果，dataclass）

| 字段 | 类型 | 说明 |
|------|------|------|
| `tenant_id` | `str` | 被查询的租户 |
| `start` | `datetime` | 查询范围起点（含） |
| `end` | `datetime` | 查询范围终点（含） |
| `request_count` | `int` | 范围内的请求总数 |
| `total_input_tokens` | `int` | 范围内累计输入 token |
| `total_output_tokens` | `int` | 范围内累计输出 token |
| `total_cost_usd` | `float` | 范围内累计成本 |

无匹配记录时，`request_count=0`，其余数值字段均为 `0`/`0.0`
（US2 验收场景 2）。

## `AuditStore` 接口（`audit.py`）

```python
class AuditStore:
    def __init__(self, db_path: str) -> None: ...
    async def record(self, entry: AuditEntry) -> None: ...
    async def query_usage(
        self, tenant_id: str, start: datetime, end: datetime
    ) -> UsageSummary: ...
    async def sum_cost_since(self, tenant_id: str, since: datetime) -> float: ...
    async def aclose(self) -> None: ...
```

`record()` 与其余方法均不做 best-effort 吞异常处理——异常处理的责任
在调用方（`AgentService._handle_locked()` 对 `record()` 的调用包在
`try/except` 内，FR-003），保持 `AuditStore` 自身接口诚实、易测试。

## `AgentService` 扩展点

| 变更 | 位置 | 兼容性 |
|------|------|--------|
| 新增 `audit_store: AuditStore \| None = None` | `__init__` | 向后兼容（默认 `None` 等价于未启用） |
| 新增 `source: str = "unknown"` | `handle()` | 向后兼容（默认值保证既有调用方零改动） |
| 新增 `QuotaExceededError` 异常 | `handle()` 可能抛出的异常集合 | 兼容式扩展（新增异常类型，不改变既有异常/返回类型） |
| 新增 `QuotaLockRegistry`（内部） | `handle()` | 按 `tenant_id` 惰性创建/复用 `asyncio.Lock`，同 `SessionLockRegistry` 写法，见下方并发说明 |

## 并发下的配额一致性（`/speckit-analyze` F1 修正）

**问题**：若配额检查只是一次"读取累计成本→比较"而不加任何同步，
同一租户并发发起的多个请求会全部读到检查发生前的同一个累计成本、
全部判定"未超限"、全部放行进入内核——这正是 spec.md Edge Cases 明确
要求避免的"明显超额放行"。且单次调用的真实成本要等
`ReactEngine.run()`（可能耗时数秒）完成后才知道，检查与写入之间的
时间窗口很大，仅靠"读时加锁"无法消除该竞态。

**决策**：当且仅当某租户配置了 `daily_cost_quota_usd` 时，
`handle()` 用一个按 `tenant_id` 惰性创建的 `asyncio.Lock`
（`QuotaLockRegistry`，与 `SessionLockRegistry` 同写法）把"配额检查 →
内核调用 → 审计记录写入"这一整段临界区串行化——同一租户在同一时刻
最多只有一个请求处于"配额相关"的处理阶段，从根本上消除竞态，而不是
仅仅缩小竞态窗口。未配置配额的租户完全不受影响（不经过此锁，
FR-006/SC-006，零额外开销）。这是"最简实现优先"下能完全消除该竞态
的最简单方案——为了让配额语义在配置了配额的租户身上更可预期，接受
这些租户的请求按顺序处理（而非像其他租户一样自由并发）这一权衡。

**加锁顺序**：为避免与既有 `SessionLockRegistry`（按 `session_id`）
产生死锁风险，固定加锁顺序为"先按 `tenant_id` 的配额锁（如适用），
再按 `session_id` 的会话锁（如适用）"，任何路径都不会反向获取，
不存在锁顺序反转导致死锁的可能。

## 状态转换（`handle()`/`_handle_locked()` 新增的前置检查）

```text
进入 handle()
  → audit_store 存在 且 租户配置了 daily_cost_quota_usd？
      → 是：acquire QuotaLockRegistry.get_lock(tenant_id)（本次调用
             结束前持有）
      → 否：不加锁，直接继续（不影响既有并发行为）
  → （若提供 session_id）acquire SessionLockRegistry.get_lock(session_id)
  → 进入 _handle_locked()：
      → 配额已配置？
          → sum_cost_since(tenant_id, 今日 UTC 零点) >= quota？
              → 是：抛 QuotaExceededError（不触发
                    ReactEngine/LLMProvider；释放上述已持有的锁）
              → 否：继续
      → （原有流程：加载历史 → 拼接 goal → 构造
         _UsageTrackingProvider 包裹的 ReactEngine → run）
      → 成功：audit_store 非空时 best-effort record(status="success")
      → 失败：audit_store 非空时 best-effort record(status="failure")，
         而后重新抛出原异常
  → 释放已持有的锁（session 锁、配额锁，按获取的逆序）
```
