# Quickstart: message 多渠道收发（消息网关）

## 前置条件

- 已完成 007（`platform_service.app`）与 008（CLI，非必需但同属平台层）。
- 一份平台配置文件，`channels` 字段至少配置一个渠道实例（结构见
  [examples/platform_config.example.json](../../examples/platform_config.example.json)），
  `callback_url` 指向一个可接收 JSON POST 的地址（真实验证时可用
  https://webhook.site 之类的临时回调地址；无网络验证见下方第 4 节）。

## 1. 配置

编辑平台配置文件，新增：

```json
{
  "channels": [
    {
      "channel_id": "demo-channel",
      "tenant_id": "tenant-demo",
      "callback_url": "https://your-callback-endpoint.example/receive"
    }
  ],
  "callback_timeout_seconds": 10.0,
  "callback_max_retries": 3
}
```

## 2. 启动服务（同 007）

```powershell
$env:PLATFORM_SERVICE_CONFIG = "path/to/config.json"
.venv\Scripts\uvicorn platform_service.app:app --port 8000
```

## 3. 投递一条消息

```powershell
curl -X POST http://localhost:8000/v1/messages/inbound `
  -H "Content-Type: application/json" `
  -d '{"channel_id":"demo-channel","external_message_id":"msg-1","sender":"user-1","text":"1+1等于几？"}'
```

**预期输出**：立即收到 `202 Accepted`，响应体
`{"accepted": true, "duplicate": false}`；随后（后台异步完成）配置的
`callback_url` 收到一次 POST，内容包含 `status="success"` 与最终答案。

## 4. 无网络验证（stub provider + 回调记录器，供自动化测试/CI 使用）

单元测试与 `examples/demo_message_gateway.py` 均通过向
`build_message_gateway()` 注入用 `httpx.MockTransport` 构造的 stub
`AgentService` provider 与"回调记录器" `httpx.AsyncClient`（记录每次
收到的回调 payload），验证成功/渠道未识别/重复投递/内核失败四种场景，
无需真实网络：

```powershell
.venv\Scripts\python examples\demo_message_gateway.py
.venv\Scripts\python -m pytest tests/unit/platform_service/test_message_gateway.py tests/unit/platform_service/test_app_messages.py -v
```

**预期输出**：demo 脚本依次打印四种场景的处理结果与（如适用）收到的
出站回调 payload；pytest 全绿。

## 5. 失败场景验证

| 场景 | 请求 | 预期响应 |
|------|------|---------|
| 渠道未识别 | `channel_id` 不在配置的 `channels` 中 | `404` |
| 参数校验失败 | 缺少 `text` 字段 | `422` |
| 重复投递 | 相同 `channel_id`+`external_message_id` 投递两次 | 第二次 `202`，`duplicate=true`，且只收到一次出站回调 |

## 6. 会话延续验证

连续投递两条共享同一 `channel_id` 与同一 `conversation_id` 的消息，
验证第二条消息对应的出站回调 `answer` 体现第一条消息积累的会话上下文
（复用 003 会话记忆，与 007/008 的 `session_id` 语义一致）。
