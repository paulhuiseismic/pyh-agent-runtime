# Data Model: 内核骨架与 provider 模块

**Date**: 2026-07-25 | **Plan**: [plan.md](plan.md) | 决策依据见 [research.md](research.md)

所有结构为 frozen dataclass（不可变），定义于 `src/kernel/provider/models.py`；
异常定义于 `src/kernel/provider/errors.py`。

## Message

对话消息（内核统一格式，OpenAI 兼容语义）。

| 字段 | 类型 | 约束 |
|------|------|------|
| role | str | 必填，`system` / `user` / `assistant` / `tool` 之一 |
| content | str | 必填，非空 |

## Limits（限额配置）

| 字段 | 类型 | 约束 | 安全默认值 |
|------|------|------|------------|
| timeout_seconds | float | > 0，必须有限值 | 60.0 |
| max_total_tokens | int | > 0（输入+输出合计上限） | 8192 |
| max_cost_usd | float | > 0 | 0.50 |

校验规则：任何字段 ≤ 0、NaN、inf → `InvalidRequestError`。
不存在表示"无限制"的取值。

## PriceTable（模型单价表）

| 字段 | 类型 | 说明 |
|------|------|------|
| prices | dict[str, ModelPrice] | key = 模型名 |

**ModelPrice**: `input_per_1k_usd: float`（≥0）、`output_per_1k_usd: float`（≥0）。

规则：请求的模型不在表中 → 调用前抛 `InvalidRequestError`（无单价即无法执行成本控制）。

## LLMRequest

| 字段 | 类型 | 约束 |
|------|------|------|
| tenant_id | str | 必填，非空、去空白后非空；缺失/空 → 发出前拒绝 |
| model | str | 必填，非空；必须在 PriceTable 中有单价 |
| messages | list[Message] | 必填，至少 1 条 |
| limits | Limits | 可选，缺省用安全默认值 |
| temperature | float \| None | 可选，[0, 2]；None 则不传给 proxy |

## TokenUsage

| 字段 | 类型 | 说明 |
|------|------|------|
| input_tokens | int | proxy 返回 `usage.prompt_tokens` |
| output_tokens | int | proxy 返回 `usage.completion_tokens` |
| total_tokens | int | 两者之和 |

## LLMResponse

| 字段 | 类型 | 说明 |
|------|------|------|
| content | str | 模型输出文本 |
| model | str | 实际响应模型（proxy 返回值） |
| usage | TokenUsage | token 用量 |
| cost_usd | float | 本地按 PriceTable 计算 |
| finish_reason | str | proxy 返回值（如 `stop` / `length`） |

## 异常层级（调用失败结果）

```text
ProviderError(Exception)
├── InvalidRequestError        # 参数校验失败（缺 tenant_id、非法限额、无单价……）
├── CallTimeoutError           # 超过 timeout_seconds；携带 timeout_seconds
├── TokenLimitExceededError    # 携带 actual_tokens, max_total_tokens
├── CostLimitExceededError     # 携带 actual_cost_usd, max_cost_usd
├── ProxyConnectionError       # 连接失败/DNS 失败/proxy 返回 HTTP 4xx-5xx（统称"proxy 不可用"）；携带底层原因或状态码；不自动重试
└── MalformedResponseError     # 响应缺少必要字段/JSON 非法；携带缺失字段说明
```

所有超限异常必须同时携带"实际值"与"上限值"（FR-005 / SC-003）。

## 调用遥测记录（span 属性契约）

每次 `complete()` 调用（含抛异常路径）产生一条 span：

| 属性 | 值 | 必带 |
|------|-----|------|
| span name | `chat {request.model}` | ✅ |
| `tenant_id` | request.tenant_id | ✅（宪法 V） |
| `gen_ai.operation.name` | `chat` | ✅ |
| `gen_ai.request.model` | request.model | ✅ |
| `gen_ai.response.model` | response.model | 成功时 |
| `gen_ai.usage.input_tokens` | usage.input_tokens | 成功时 |
| `gen_ai.usage.output_tokens` | usage.output_tokens | 成功时 |
| `gen_ai.usage.cost` | cost_usd | 成功时 |
| span status | OK / ERROR + 异常类名 | ✅ |

规则：span 发出失败不影响调用结果（FR-007）；参数校验失败发生在 span 创建前的
拒绝（缺 tenant_id）不产生对外请求，但仍记录一条 ERROR span（tenant_id 缺失时
以 `"<missing>"` 占位，保证审计可见被拒绝的调用）。

## 状态流转（一次调用）

```text
构造请求 → 校验(tenant_id/limits/单价/消息) ──失败→ InvalidRequestError
        → 输入粗估超预算? ──是→ TokenLimitExceededError
        → POST proxy（显式 timeout, max_tokens=剩余预算）
            ├─ 超时 → CallTimeoutError
            ├─ 连接失败 → ProxyConnectionError
            ├─ 响应格式非法 → MalformedResponseError
        → 校验 usage ≤ max_total_tokens ──超→ TokenLimitExceededError
        → 计算成本 ≤ max_cost_usd ──超→ CostLimitExceededError
        → 返回 LLMResponse
（全路径 finally：发出 span）
```

## 骨架接口（react/memory/tool，本 feature 仅定义）

- **ReactLoop (Protocol)**: `async run(goal: str, *, tenant_id: str, max_steps: int) -> str`
  —— `max_steps` 必填、> 0（宪法 VI 预留）。
- **Memory (Protocol)**: `async load(session_id: str, *, tenant_id: str) -> list[Message]`；
  `async append(session_id: str, message: Message, *, tenant_id: str) -> None`
  —— 所有操作必带 `tenant_id`（多租户隔离键）。
- **Tool (Protocol)**: `name: str`、`description: str`、
  `async invoke(arguments: dict, *, tenant_id: str) -> str`。
- 各配一个最小占位实现（如 `NoopMemory`、`EchoTool`、`SingleShotReactLoop`），
  仅用于骨架可实例化与测试锁定接口签名。
