"""Provider 异常层级：类型化失败结果（见 specs/001 data-model.md）。

所有超限异常必须同时携带实际值与上限值（FR-005 / SC-003）。
"""


class ProviderError(Exception):
    """provider 所有失败的基类。"""


class InvalidRequestError(ProviderError):
    """参数校验失败：缺 tenant_id、非法限额、模型无单价等；发出 HTTP 请求前抛出。"""


class CallTimeoutError(ProviderError):
    def __init__(self, timeout_seconds: float):
        self.timeout_seconds = timeout_seconds
        super().__init__(f"LLM 调用超过显式超时 {timeout_seconds}s")


class TokenLimitExceededError(ProviderError):
    def __init__(self, actual_tokens: int, max_total_tokens: int):
        self.actual_tokens = actual_tokens
        self.max_total_tokens = max_total_tokens
        super().__init__(
            f"token 用量 {actual_tokens} 超过上限 {max_total_tokens}"
        )


class CostLimitExceededError(ProviderError):
    def __init__(self, actual_cost_usd: float, max_cost_usd: float):
        self.actual_cost_usd = actual_cost_usd
        self.max_cost_usd = max_cost_usd
        super().__init__(
            f"调用成本 {actual_cost_usd:.6f} USD 超过上限 {max_cost_usd:.6f} USD"
        )


class ProxyConnectionError(ProviderError):
    """proxy 不可用：连接失败 / DNS 失败 / HTTP 4xx-5xx。不自动重试。"""

    def __init__(self, detail: str, status_code: int | None = None):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"模型路由服务不可用: {detail}")


class MalformedResponseError(ProviderError):
    """proxy 返回 200 但响应缺少必要字段或 JSON 非法。"""

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(f"模型路由服务响应格式非法: {detail}")
