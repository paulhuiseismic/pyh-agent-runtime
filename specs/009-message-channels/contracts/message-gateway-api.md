# Contract: 消息网关 REST 入口 + 出站回调

**Consumer**: 外部消息渠道（webhook 转发方）
**Provider**: `platform_service`（在 007 `AgentService`/`app.py` 之上组装）

数据结构见 [data-model.md](../data-model.md)。

## 入站接入接口

### `POST /v1/messages/inbound`

**请求体**（`InboundMessage`）：

```json
{
  "channel_id": "字符串，必填，非空",
  "external_message_id": "字符串，必填，非空",
  "sender": "字符串，必填，非空",
  "text": "字符串，必填，非空",
  "conversation_id": "字符串，可选"
}
```

**响应**：

| 场景 | HTTP 状态码 | 响应体要点 |
|------|------------|-----------|
| 接受（新消息，已调度后台处理） | 202 | `InboundAcceptResult(accepted=true, duplicate=false)` |
| 接受（重复投递，未二次调度） | 202 | `InboundAcceptResult(accepted=true, duplicate=true)` |
| 渠道未识别（FR-002） | 404 | 错误类型标识 + 可读原因 |
| 请求体校验失败（缺字段/类型错误） | 422 | FastAPI/pydantic 内置的校验错误详情 |

**行为契约**：

1. 端点 MUST 在返回响应前完成"渠道识别"与"重复投递检测"，MUST NOT
   在这两步完成之前触发任何后台处理（FR-002/FR-006）。
2. 端点的响应延迟 MUST NOT 随后台 agent 处理耗时增长（SC-001）——
   通过 `asyncio.create_task` 调度后台处理、不 `await` 其完成来保证。
3. 重复投递（相同 `channel_id` + `external_message_id`）MUST NOT
   触发第二次后台处理或第二次出站回调（FR-006/SC-003）。

## 出站回调接口（本服务作为调用方）

消息网关处理完成后，MUST 向该消息所属 `ChannelConfig.callback_url`
发起一次 `POST` 请求（显式超时 `callback_timeout_seconds`，失败时
按 `callback_max_retries` 有限重试，见 research.md R3）：

```json
{
  "external_message_id": "对应入站消息的 external_message_id",
  "conversation_id": "对应入站消息的 conversation_id（可能为 null）",
  "status": "success | kernel_error | timeout",
  "answer": "成功时为最终结果文本，否则为 null",
  "error": "失败时为可读原因，否则为 null"
}
```

**行为契约**：

1. 每一条被接受（非重复）的消息，无论处理成功或失败，MUST 最终触发
   一次出站回调尝试（FR-004/SC-004）。
2. 出站回调本身的失败（目标不可达、超时、非 2xx 响应）MUST 按
   `callback_max_retries` 有限次数重试，MUST NOT 无限重试
   （FR-008，呼应宪法原则 IV）。
3. 出站回调全部重试仍失败时，MUST NOT 影响本进程的稳定性或后续消息
   的正常处理（仅记录日志）。

## `MessageGateway` 内部契约（供 `app.py` 调用）

```python
from platform_service.message_gateway import MessageGateway, build_message_gateway

gateway: MessageGateway = await build_message_gateway(config, agent_service=agent_service)
result = await gateway.handle_inbound(message)  # InboundMessage -> InboundAcceptResult
```

**行为契约**：

1. `handle_inbound()` MUST NOT 阻塞等待后台处理完成——调用方（HTTP
   端点）在其返回后应立即把结果转换为 HTTP 响应。
2. `handle_inbound()` 触发的后台处理 MUST 复用与 007/008 完全一致的
   `AgentService.handle()` 调用与 `platform_request_span` 遥测包裹，
   MUST NOT 重新实现租户识别或内核调用组合逻辑（FR-003/SC-007）。

## 兼容性承诺

- 不修改 001-008 已冻结的任何内核/平台层公共接口（`AgentService.handle()`
  签名、`resolve_tenant`/`build_agent_service` 行为、既有 `/v1/agent/run`
  端点行为均不变）。
- `PlatformConfig` 新增字段（`channels`/`callback_timeout_seconds`/
  `callback_max_retries`）均有安全默认值，不破坏 007/008 已有配置文件
  的向后兼容性。
