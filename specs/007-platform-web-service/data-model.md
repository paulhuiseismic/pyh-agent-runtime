# Data Model: 平台服务层 + web service（REST API）

**Date**: 2026-08-01 | **Plan**: [plan.md](plan.md) | 决策依据见 [research.md](research.md)

## PlatformConfig / TenantConfig（配置，`config.py`）

| 字段 | 类型 | 说明 |
|------|------|------|
| `TenantConfig.api_key` | str | 该租户对应的静态 API Key（FR-011） |
| `TenantConfig.tenant_id` | str | 租户标识 |
| `TenantConfig.max_concurrent_requests` | int | 该租户的并发上限，> 0（FR-004） |
| `PlatformConfig.tenants` | list[TenantConfig] | 全部已配置租户 |
| `PlatformConfig.global_max_concurrent_requests` | int | 平台级并发上限，> 0（FR-005） |
| `PlatformConfig.request_timeout_seconds` | float | 单次请求整体处理超时，> 0（FR-009） |
| `PlatformConfig.model` | str | 默认使用的模型标识（透传给 001 `LLMProvider`/002 `ReactEngine`） |
| `PlatformConfig.max_steps` | int | 透传给 002 `ReactEngine.run()` 的最大步数，> 0 |
| `PlatformConfig.provider_base_url` | str | 必填，001 `LLMProvider(base_url=...)` 的 LiteLLM proxy 地址（无合理默认值，缺失时启动即失败，FR-013） |
| `PlatformConfig.provider_api_key` | str \| None | 可选，透传给 001 `LLMProvider(api_key=...)` |
| `PlatformConfig.price_table` | `kernel.provider.models.PriceTable` | 必填，`model` 字段对应的模型 MUST 在其中配置单价，否则 001 `PriceTable.price_for()` 会拒绝调用（呼应宪法原则 IV 成本上限，FR-013） |
| `PlatformConfig.provider_call_limits` | `kernel.provider.models.Limits` \| None | 可选，透传给 001 `LLMProvider` 作为单次调用的 token/成本/超时上限，缺省时使用 001 已有的安全默认值 |
| `PlatformConfig.mcp_servers` | list[`kernel.tool.McpServerConfig`] | 可选，默认空列表；应用启动时依次 `connect()` 并 `register_mcp_tools()` 进共享 `ToolRegistry`（research.md R4/R7）；v1 不提供沙箱工具（005）的配置项，`ToolRegistry` 除 MCP 工具外为空也是合法状态（FR-014） |

任一数值字段 ≤ 0、`provider_base_url` 为空、`price_table` 未包含 `model`
对应的单价、或存在重复 `api_key`/`tenant_id` → 构造时抛
`InvalidRequestError`（复用 001 异常，与 003/004/005/006 的校验风格一致）。

## 平台层异常层级（`errors.py`）

```text
AuthenticationError(Exception)       # 未识别出合法租户（FR-002）：detail: str
ConcurrencyLimitExceededError(Exception)  # 并发上限超出（FR-004/FR-005）：
                                           # scope: "tenant" | "global"
RequestTimeoutError(Exception)       # 请求整体处理超时（FR-009）：
                                      # timeout_seconds: float
```

三者均独立于内核（`kernel.*`）已有的异常层级——它们描述的是平台层自身的
失败原因，与内核调用失败（001 `ProviderError`、002
`StepBudgetExceededError`、005/006 `SandboxError`/`McpError` 等）在
`app.py` 中被分别映射为不同的 HTTP 状态码（对应 FR-007 的"可区分响应"）。

## AgentRunRequest / AgentRunResult（`models.py`，pydantic）

| 字段（AgentRunRequest） | 类型 | 说明 |
|------|------|------|
| `goal` | str | 用户的目标/问题描述（必填，非空） |
| `session_id` | str \| None | 可选会话标识，复用 003 会话记忆（FR-008） |

| 字段（AgentRunResult） | 类型 | 说明 |
|------|------|------|
| `status` | `Literal["success"]` | 仅在成功路径构造此结果（失败路径见下） |
| `answer` | str | ReAct 循环产出的最终答案 |
| `session_id` | str \| None | 回显本次使用的 session_id（若有） |

失败路径不复用 `AgentRunResult`，而是由 `app.py` 直接把对应异常映射为
FastAPI 的错误响应（见 contracts/agent-run-api.md），保持"成功结果"与
"错误响应"两种模型不混用一个 status 字段判断，避免调用方误判。

## ConcurrencyScheduler（`scheduler.py`，见 research.md R2）

```python
class ConcurrencyScheduler:
    def __init__(self, config: PlatformConfig) -> None: ...

    async def try_acquire(self, tenant_id: str) -> None: ...
        # 锁保护的检查+自增；租户或全局任一超限 → ConcurrencyLimitExceededError

    def release(self, tenant_id: str) -> None: ...
        # 对应 try_acquire 的自减，MUST 在 finally 块调用，不抛异常
```

## SessionLockRegistry（`agent_service.py`，见 FR-015）

```python
class SessionLockRegistry:
    def get_lock(self, session_id: str) -> asyncio.Lock: ...
        # 按 session_id 惰性创建/复用一个 asyncio.Lock；不同 session_id
        # 返回不同的 Lock 实例，互不阻塞（FR-015 后半句）
```

进程内维护一个 `dict[str, asyncio.Lock]`（惰性创建，不预先枚举所有可能的
`session_id`）；`AgentService.handle()` 在提供了 `session_id` 时，把
「加载历史 → 拼接 goal → 运行 ReAct → 写回历史」这一整段序列包裹在对应
`session_id` 的锁内（未提供 `session_id` 时不加锁，因为没有可交叉写入的
共享状态）。锁的粒度只到"同一 session_id 的处理串行化"，不同 session_id
之间、或未提供 session_id 的请求之间 MUST NOT 互相等待。

## AgentService（`agent_service.py`）

```python
class AgentService:
    def __init__(
        self, *, provider: LLMProvider, tool_registry: ToolRegistry,
        session_memory: SqliteMemory, long_term_memory: LongTermMemory,
        config: PlatformConfig,
    ) -> None: ...

    async def handle(
        self, request: AgentRunRequest, *, tenant_id: str,
    ) -> AgentRunResult: ...
```

`handle()` 内部序列（对应 research.md R3；`provider` 由 `PlatformConfig.
provider_base_url`/`provider_api_key`/`price_table`/`provider_call_limits`
构造，`tool_registry` 由 `PlatformConfig.mcp_servers` 构造，均在应用启动时
一次性完成，见 research.md R4）：

```text
0. 若 request.session_id 提供 → 先 await session_lock_registry
   .get_lock(session_id) 获取该 session 专属的锁，本次处理全程持有
   （FR-015）；未提供 session_id 则跳过加锁
1. 若 request.session_id 提供 → session_memory.load(session_id, tenant_id)
   取得历史消息；否则历史为空
2. 查询 long_term_memory.query(tenant_id=tenant_id) 取得已提炼事实（可为空）
3. 拼接 goal 字符串：[长期记忆事实（如有）] + [会话历史（如有）] + request.goal
4. 构造 ReactEngine(provider=self._provider, tools=tool_registry.as_dict(),
   model=config.model, max_step_limits=...)
5. await engine.run(拼接后的 goal, tenant_id=tenant_id, max_steps=config.max_steps)
   → 最终答案（内核抛出的任何异常直接向上传播，由 app.py 统一映射；
   若在此步之前或之中抛出异常，第 0 步获取的锁仍会在 finally 中正常释放）
6. 若 request.session_id 提供：
   session_memory.append(session_id, Message(role="user", content=request.goal), ...)
   session_memory.append(session_id, Message(role="assistant", content=最终答案), ...)
7. best-effort（失败不影响本次返回）：
   long_term_memory.extract(该会话最新历史, tenant_id=tenant_id)
8. 返回 AgentRunResult(status="success", answer=最终答案, session_id=...)
   （第 0 步获取的锁在 finally 中释放）
```

## 状态流转（一次 REST 请求）

```text
POST /v1/agent/run
  → 从请求头解析 API Key → auth.resolve_tenant(api_key)
      ├─ 未识别 → AuthenticationError → 401
      └─ 成功 → tenant_id
  → scheduler.try_acquire(tenant_id)
      ├─ 超出租户/全局上限 → ConcurrencyLimitExceededError → 429
      └─ 成功
  → 请求体校验（FastAPI + pydantic，AgentRunRequest）
      └─ 失败 → 422（FastAPI 内置行为，满足 FR-007 的"参数校验失败"类别）
  → asyncio.wait_for(agent_service.handle(request, tenant_id=tenant_id),
                      timeout=config.request_timeout_seconds)
      ├─ 超时 → RequestTimeoutError → 504
      ├─ 内核异常（ProviderError/StepBudgetExceededError/SandboxError/
      │   McpError 等） → 502（统一归类为"内核处理失败"）
      └─ 成功 → AgentRunResult → 200
  → finally: scheduler.release(tenant_id)
```

## 遥测 span 契约

### `platform.request`（新增）

| 属性 | 值 |
|------|-----|
| span name | `platform.request` |
| `tenant_id` | 解析出的租户标识（鉴权失败时无此属性，span 提前以 ERROR 结束） |
| `session_id` | 请求携带的 session_id（若有） |
| `result` | `success` / `auth_failed` / `concurrency_exceeded` / `validation_failed` / `kernel_error` / `timeout` |
| 父子关系 | 作为本次请求触发的全部内核 span（`chat {model}`/`react.step`/
  `memory.*`/`tool.invoke`/`mcp.connect` 等）的根 span，验证方式同 001-006
  已确立的"parent-child span"断言风格（`span.parent.span_id ==
  root_span.context.span_id`），不仅靠 span 数量匹配 |
| span status | 成功 OK；任意失败类型 ERROR + 异常类名 |
