# Contract: LiteLLM proxy HTTP 依赖契约（子集）

**Consumer**: `kernel.provider`
**Provider**: 独立部署的 LiteLLM proxy（OpenAI 兼容接口）

provider 只依赖以下契约子集。测试中 `httpx.MockTransport` 模拟的就是本契约；
任何实现此契约的 OpenAI 兼容路由服务均可替换 LiteLLM（宪法原则 III 可替换性）。

## 请求

```http
POST {base_url}/v1/chat/completions
Authorization: Bearer {api_key}      # 可选，配置了 api_key 时携带
Content-Type: application/json
```

```json
{
  "model": "<request.model>",
  "messages": [{"role": "user", "content": "..."}],
  "max_tokens": 4096,
  "temperature": 0.7,
  "stream": false
}
```

- `max_tokens` = `limits.max_total_tokens - 输入粗估 tokens`（剩余输出预算）
- `temperature` 仅在请求中显式提供时传递
- `stream` 恒为 `false`（本 feature 不支持流式）

## 成功响应（HTTP 200）

provider 依赖的最小字段集（缺任一 → `MalformedResponseError`）：

```json
{
  "model": "gpt-4o-2024-08-06",
  "choices": [
    {
      "message": {"role": "assistant", "content": "..."},
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 123,
    "completion_tokens": 456,
    "total_tokens": 579
  }
}
```

忽略响应中的其余字段（含 LiteLLM 私有扩展如 `x-litellm-*` 头——
不依赖其成本头，成本一律本地计算，见 research.md R8）。

## 错误映射

| proxy 行为 | provider 异常 |
|-----------|---------------|
| 响应超过 timeout_seconds | `CallTimeoutError` |
| 连接拒绝 / DNS 失败 | `ProxyConnectionError` |
| HTTP 4xx/5xx | `ProxyConnectionError`（携带状态码与响应体摘要） |
| 200 但缺少必要字段 / JSON 非法 | `MalformedResponseError` |
| 200 但 `usage.total_tokens` > 限额 | `TokenLimitExceededError` |

## 部署形态（开发环境参考，非交付物）

```bash
docker run -p 4000:4000 \
  -v ./litellm-config.yaml:/app/config.yaml \
  ghcr.io/berriai/litellm:main-stable --config /app/config.yaml
```

仅使用 LiteLLM 开源核心能力（路由、限额）；不使用 `enterprise/` 目录功能
（license 约束见 THIRD_PARTY.md）。
