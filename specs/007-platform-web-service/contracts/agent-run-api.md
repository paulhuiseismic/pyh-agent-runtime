# Contract: Agent 调用 REST API + AgentService 内部契约

**Consumer**: 外部调用方（本 feature 的 REST 接口）、未来 CLI 入口（008，
直接调用 `AgentService`，不经过 HTTP）
**Provider**: `platform_service`（在 001-006 内核能力之上组装）

数据结构见 [data-model.md](../data-model.md)。

## REST 接口

### `POST /v1/agent/run`

**请求头**：`X-API-Key: <该租户的 API Key>`（FR-011）

**请求体**（`AgentRunRequest`）：

```json
{
  "goal": "字符串，必填，非空",
  "session_id": "字符串，可选"
}
```

**响应**：

| 场景 | HTTP 状态码 | 响应体要点 |
|------|------------|-----------|
| 成功 | 200 | `AgentRunResult`（`status="success"`, `answer`, `session_id`） |
| 租户身份识别失败（FR-002） | 401 | 错误类型标识 + 可读原因 |
| 并发上限超出（FR-004/FR-005） | 429 | 错误类型标识 + 超限范围（`tenant`/`global`） |
| 请求体校验失败（缺字段/类型错误） | 422 | FastAPI/pydantic 内置的校验错误详情 |
| 内核处理失败（LLM 调用失败/ReAct 步数耗尽/工具执行失败等） | 502 | 错误类型标识 + 内核异常的可读信息 |
| 请求整体处理超时（FR-007/FR-009） | 504 | 错误类型标识 + 配置的超时秒数 |

**启动期失败**：`provider_base_url` 缺失、`price_table` 未覆盖
`PlatformConfig.model` 对应的模型、或任一 `TenantConfig`/`PlatformConfig`
数值字段非法时，应用 MUST 在启动阶段（构造 `PlatformConfig`/`AgentService`
时）直接抛异常终止启动，MUST NOT 以"运行中但请求必然失败"的状态对外提供
服务（FR-013/FR-014）。

## `AgentService` 内部契约（供未来 CLI 复用）

```python
from platform_service import AgentService, AgentRunRequest

service: AgentService = ...  # 应用启动时构建一次（research.md R4）
result = await service.handle(
    AgentRunRequest(goal="...", session_id="..."),
    tenant_id="租户标识（由调用方自行完成鉴权后传入，AgentService 不做鉴权）",
)
```

## 行为契约

1. `AgentService.handle()` MUST NOT 感知调用方是 REST 还是其他入口；
   鉴权、并发调度、HTTP 状态码映射 MUST 全部在 `AgentService` 之外完成
   （FR-003/SC-006）。
2. 未识别出合法租户的请求 MUST 在 `AgentService.handle()` 被调用之前
   （即触发任何内核调用之前）就被拒绝（FR-002/SC-002）。
3. 并发上限超出时 MUST 立即返回明确响应，MUST NOT 让调用方被无限期挂起
   （FR-004/FR-005/FR-012/SC-003）。
4. `AgentService.handle()` 触发的每一次内核调用 MUST 携带与请求一致的
   `tenant_id`（FR-006/SC-005）。
5. 提供了 `session_id` 的请求 MUST 复用该会话此前积累的历史上下文
   （FR-008）；未提供时 MUST 视为无历史上下文的全新调用。
6. 单次请求的整体处理 MUST 有显式超时，超时 MUST 返回明确响应而非无限期
   等待（FR-009）。
7. 一个租户达到其并发上限 MUST NOT 影响其他租户请求的正常处理
   （spec US2 验收场景 3）。
8. 同一 `session_id` 的并发请求 MUST 被串行化处理，不产生会话历史顺序
   错乱或更新丢失；不同 `session_id`（含未提供 `session_id`）的请求
   MUST NOT 因此互相阻塞（FR-015/SC-007）。
9. 应用 MUST 在启动阶段校验 provider 连接信息与模型成本单价配置完整，
   缺失或无效时 MUST 直接终止启动，MUST NOT 以"运行中但请求必然失败"
   的状态对外提供服务（FR-013/FR-014）。

## 兼容性承诺

- 不修改 001-006 已冻结的任何内核公共接口。
- `AgentRunRequest`/`AgentRunResult` 字段只增不删，新增字段须有安全默认值。
- `AgentService.handle()` 的方法签名冻结后只做兼容式扩展，保证 008（CLI）
  可以直接复用而不需要跟随改动。
