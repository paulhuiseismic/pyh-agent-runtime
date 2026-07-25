# Contract: provider 公共 Python 接口

**Consumer**: 内核 react 模块（后续 feature）、平台层调度器
**Provider**: `kernel.provider`

数据结构与异常的完整定义见 [data-model.md](../data-model.md)，此处只定义调用契约。

## 公共导出（`kernel.provider` 包级）

```python
from kernel.provider import (
    LLMProvider,        # 调用入口
    LLMRequest, LLMResponse, Message, Limits, PriceTable, ModelPrice, TokenUsage,
    ProviderError, InvalidRequestError, CallTimeoutError,
    TokenLimitExceededError, CostLimitExceededError,
    ProxyConnectionError, MalformedResponseError,
)
```

## LLMProvider

```python
class LLMProvider:
    def __init__(
        self,
        *,
        base_url: str,                    # LiteLLM proxy 地址，如 http://litellm.internal:4000
        price_table: PriceTable,          # 模型单价表（必填，成本控制依据）
        api_key: str | None = None,       # proxy 虚拟 key，经 Authorization: Bearer 传递
        default_limits: Limits = Limits(),# 安全默认限额
        transport: httpx.AsyncBaseTransport | None = None,  # 测试注入 MockTransport
    ) -> None: ...

    async def complete(self, request: LLMRequest) -> LLMResponse: ...

    async def aclose(self) -> None:       # 释放底层 HTTP 连接
```

## 行为契约

1. `complete()` 是唯一调用入口，非流式，幂等无副作用（除遥测）。
2. 校验顺序：请求结构 → tenant_id → limits 合法性 → 模型单价存在 → 输入粗估。
   任何校验失败在发出 HTTP 请求**之前**抛 `InvalidRequestError` 或
   `TokenLimitExceededError`。
3. 成功返回 `LLMResponse`；失败抛 `ProviderError` 子类，**不返回 None、
   不静默降级**。调用方可按异常类型编程分支。
4. 每次调用（含全部失败路径）发出一条 span，属性契约见
   [data-model.md](../data-model.md#调用遥测记录span-属性契约)；
   遥测异常不影响本方法的返回/抛出。
5. 并发安全：同一实例可被多协程并发调用，各调用的超时/限额/span 互不串扰。
6. 不重试：任何失败直接上抛。重试策略属于调用方/平台层决策。

## 兼容性承诺

- 本契约冻结后，字段只增不删、不改语义；新增字段必须有默认值
  （宪法："不破坏既有接口契约"）。
- 流式接口（如 `stream()`）为未来扩展，不影响 `complete()` 契约。
