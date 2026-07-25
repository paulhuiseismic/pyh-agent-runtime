"""LLMProvider：经 LiteLLM proxy（OpenAI 兼容 HTTP）的受保护 LLM 调用。

契约见 specs/001-kernel-provider/contracts/provider-api.md 与
litellm-proxy-contract.md；调用状态机见 data-model.md。
"""

import asyncio

import httpx

from kernel.provider.errors import (
    CallTimeoutError,
    CostLimitExceededError,
    InvalidRequestError,
    MalformedResponseError,
    ProviderError,
    ProxyConnectionError,
    TokenLimitExceededError,
)
from kernel.provider.models import (
    Limits,
    LLMRequest,
    LLMResponse,
    PriceTable,
    TokenUsage,
)
from kernel.provider.pricing import calculate_cost, estimate_input_tokens

_CHAT_COMPLETIONS_PATH = "/v1/chat/completions"


class LLMProvider:
    def __init__(
        self,
        *,
        base_url: str,
        price_table: PriceTable,
        api_key: str | None = None,
        default_limits: Limits | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not base_url:
            raise InvalidRequestError("base_url 必填")
        self._price_table = price_table
        self._default_limits = default_limits or Limits()
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        # 超时按每次请求显式传入（宪法原则 IV），client 级不设隐式默认
        self._client = httpx.AsyncClient(
            base_url=base_url, headers=headers, transport=transport
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def complete(self, request: LLMRequest) -> LLMResponse:
        limits = request.limits or self._default_limits

        # 校验链：请求结构/tenant_id/limits 已在 dataclass 构造时校验；
        # 此处校验单价存在与输入粗估预算（发出 HTTP 请求之前）
        self._price_table.price_for(request.model)
        estimated_input = estimate_input_tokens(request)
        if estimated_input >= limits.max_total_tokens:
            raise TokenLimitExceededError(
                actual_tokens=estimated_input,
                max_total_tokens=limits.max_total_tokens,
            )

        payload = {
            "model": request.model,
            "messages": [
                {"role": m.role, "content": m.content} for m in request.messages
            ],
            "max_tokens": limits.max_total_tokens - estimated_input,
            "stream": False,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature

        try:
            # asyncio.timeout 兜底保证"必然终止"（SC-003），不依赖传输层
            # 是否履行 httpx 超时（如测试用的 MockTransport 就不履行）
            async with asyncio.timeout(limits.timeout_seconds):
                response = await self._client.post(
                    _CHAT_COMPLETIONS_PATH,
                    json=payload,
                    timeout=limits.timeout_seconds,
                )
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise CallTimeoutError(limits.timeout_seconds) from exc
        except httpx.HTTPError as exc:
            raise ProxyConnectionError(detail=str(exc)) from exc

        if response.status_code != 200:
            raise ProxyConnectionError(
                detail=f"HTTP {response.status_code}: {response.text[:200]}",
                status_code=response.status_code,
            )

        parsed = self._parse_response(response, request.model)
        usage = parsed.usage
        if usage.total_tokens > limits.max_total_tokens:
            raise TokenLimitExceededError(
                actual_tokens=usage.total_tokens,
                max_total_tokens=limits.max_total_tokens,
            )
        if parsed.cost_usd > limits.max_cost_usd:
            raise CostLimitExceededError(
                actual_cost_usd=parsed.cost_usd,
                max_cost_usd=limits.max_cost_usd,
            )
        return parsed

    def _parse_response(self, response: httpx.Response, requested_model: str) -> LLMResponse:
        try:
            body = response.json()
        except ValueError as exc:
            raise MalformedResponseError(f"响应不是合法 JSON: {exc}") from exc
        try:
            choice = body["choices"][0]
            content = choice["message"]["content"]
            finish_reason = choice["finish_reason"]
            usage_raw = body["usage"]
            usage = TokenUsage(
                input_tokens=usage_raw["prompt_tokens"],
                output_tokens=usage_raw["completion_tokens"],
                total_tokens=usage_raw["total_tokens"],
            )
            model = body["model"]
        except (KeyError, IndexError, TypeError) as exc:
            raise MalformedResponseError(f"响应缺少必要字段: {exc!r}") from exc
        # 成本按请求模型计价（发出前已校验其单价存在）；响应模型名可能带
        # 版本后缀（如 gpt-4o-2024-08-06），仅作信息回读，不用于计价
        cost = calculate_cost(requested_model, usage, self._price_table)
        return LLMResponse(
            content=content,
            model=model,
            usage=usage,
            cost_usd=cost,
            finish_reason=finish_reason,
        )
