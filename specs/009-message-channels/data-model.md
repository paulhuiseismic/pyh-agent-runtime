# Data Model: message 多渠道收发（消息网关）

## 复用的既有实体（零改动）

- **`AgentService`**（含内部 `SessionLockRegistry`）：行为零改动，
  消息网关只是新增一个调用方，`conversation_id` 映射为
  `AgentRunRequest.session_id`。
- **`PlatformConfig`**：只做新增字段的向后兼容扩展（见下），既有字段
  语义与校验规则不变。
- **`platform_request_span`**：零改动复用，`tenant_id`/`session_id`
  语义与 007/008 完全一致。

## 新增/扩展的配置实体

### `ChannelConfig`（新增，frozen dataclass，`config.py`）

| 字段 | 类型 | 校验 |
|------|------|------|
| `channel_id` | `str` | 非空 |
| `tenant_id` | `str` | 非空 |
| `callback_url` | `str` | 非空 |
| `callback_secret` | `str \| None` | 可选，默认 `None` |

### `PlatformConfig` 新增字段

| 字段 | 类型 | 默认值 | 校验 |
|------|------|--------|------|
| `channels` | `list[ChannelConfig]` | `[]` | `channel_id` 不重复 |
| `callback_timeout_seconds` | `float` | `10.0` | `> 0` |
| `callback_max_retries` | `int` | `3` | `> 0` |

`channels` 默认空列表——未配置任何渠道时，消息网关端点对一切投递返回
"渠道未识别"（FR-002），与 007 `mcp_servers` 默认空、`ToolRegistry`
允许为空的设计风格一致。

## 新增的运行时实体（不持久化，或仅进程内存）

### `InboundMessage`（新增，pydantic，`models.py`）

| 字段 | 类型 | 必需性 |
|------|------|--------|
| `channel_id` | `str` | 必需，非空 |
| `external_message_id` | `str` | 必需，非空 |
| `sender` | `str` | 必需，非空 |
| `text` | `str` | 必需，非空 |
| `conversation_id` | `str \| None` | 可选 |

### `InboundAcceptResult`（新增，pydantic，`models.py`）

| 字段 | 类型 | 说明 |
|------|------|------|
| `accepted` | `bool` | 是否已接受（渠道识别成功、参数合法） |
| `duplicate` | `bool` | 是否为重复投递（`True` 时未二次调度处理） |

### 出站回调 Payload（不建模为 pydantic 类，由 `message_gateway.py`
以 `dict` 形式构造，供 `send_callback_with_retry` 序列化为 JSON POST
到 `ChannelConfig.callback_url`）

| 字段 | 说明 |
|------|------|
| `external_message_id` | 关联回原始入站消息 |
| `conversation_id` | 原样回传（可能为 `None`） |
| `status` | `"success"` \| `"kernel_error"` \| `"timeout"` |
| `answer` | 成功时的最终结果文本（失败时为 `None`） |
| `error` | 失败时的可读原因（成功时为 `None`） |

### `ProcessedMessageRegistry`（新增，进程内存，`message_gateway.py`）

- 内部状态：`asyncio.Lock` 保护的 `set[tuple[str, str]]`（键为
  `(channel_id, external_message_id)`）。
- `async def check_and_mark(channel_id, external_message_id) -> bool`：
  原子"查重 + 标记"，返回 `True` 表示这是第一次见到该消息（应处理），
  `False` 表示重复投递（不应二次处理）。
- 不持久化，进程重启后清空——与 spec.md Assumptions"不追求跨进程/
  重启后的强一致性去重"一致。

## 状态转换

一条入站消息的生命周期：

```text
接入请求到达
  → 解析 channel_id → 未匹配任何 ChannelConfig ⇒ 404（不进入后续状态）
  → check_and_mark(channel_id, external_message_id)
      → False（重复）⇒ 返回 InboundAcceptResult(accepted=True, duplicate=True)，
                        不调度处理
      → True（首次）⇒ 调度后台任务，返回
                        InboundAcceptResult(accepted=True, duplicate=False)
  → [后台] AgentService.handle() 执行
      → 成功 ⇒ 出站回调 status="success"
      → 超时 ⇒ 出站回调 status="timeout"
      → 其他内核异常 ⇒ 出站回调 status="kernel_error"
  → [后台] send_callback_with_retry()
      → 成功投递 ⇒ 结束
      → 达到 callback_max_retries 仍失败 ⇒ 记录警告日志，结束
        （不影响进程本身，不重新入队）
```
