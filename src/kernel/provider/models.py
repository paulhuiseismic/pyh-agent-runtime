"""Provider 数据结构：统一请求/响应与限额配置（见 specs/001 data-model.md）。"""

import math
from dataclasses import dataclass, field

from kernel.provider.errors import InvalidRequestError

VALID_ROLES = frozenset({"system", "user", "assistant", "tool"})

DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_TOTAL_TOKENS = 8192
DEFAULT_MAX_COST_USD = 0.50


def _require_positive_finite(name: str, value: float) -> None:
    # 宪法原则 IV：任何限额不允许"无限制"，故拒绝 <=0 / NaN / inf
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise InvalidRequestError(f"{name} 必须是数值，收到: {value!r}")
    if math.isnan(value) or math.isinf(value) or value <= 0:
        raise InvalidRequestError(f"{name} 必须是正的有限数值，收到: {value!r}")


@dataclass(frozen=True)
class Message:
    role: str
    content: str

    def __post_init__(self) -> None:
        if self.role not in VALID_ROLES:
            raise InvalidRequestError(
                f"message.role 必须是 {sorted(VALID_ROLES)} 之一，收到: {self.role!r}"
            )
        if not isinstance(self.content, str) or not self.content:
            raise InvalidRequestError("message.content 必须是非空字符串")


@dataclass(frozen=True)
class Limits:
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_total_tokens: int = DEFAULT_MAX_TOTAL_TOKENS
    max_cost_usd: float = DEFAULT_MAX_COST_USD

    def __post_init__(self) -> None:
        _require_positive_finite("limits.timeout_seconds", self.timeout_seconds)
        _require_positive_finite("limits.max_total_tokens", self.max_total_tokens)
        if not isinstance(self.max_total_tokens, int):
            raise InvalidRequestError(
                f"limits.max_total_tokens 必须是整数，收到: {self.max_total_tokens!r}"
            )
        _require_positive_finite("limits.max_cost_usd", self.max_cost_usd)


@dataclass(frozen=True)
class ModelPrice:
    input_per_1k_usd: float
    output_per_1k_usd: float

    def __post_init__(self) -> None:
        for name, value in (
            ("input_per_1k_usd", self.input_per_1k_usd),
            ("output_per_1k_usd", self.output_per_1k_usd),
        ):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise InvalidRequestError(f"price.{name} 必须是数值")
            if math.isnan(value) or math.isinf(value) or value < 0:
                raise InvalidRequestError(f"price.{name} 必须是非负的有限数值")


@dataclass(frozen=True)
class PriceTable:
    prices: dict[str, ModelPrice] = field(default_factory=dict)

    def price_for(self, model: str) -> ModelPrice:
        # 无单价即无法执行成本控制，必须拒绝（spec 边界规则）
        if model not in self.prices:
            raise InvalidRequestError(
                f"模型 {model!r} 未配置单价，无法执行成本控制，拒绝调用"
            )
        return self.prices[model]


@dataclass(frozen=True)
class LLMRequest:
    tenant_id: str
    model: str
    messages: tuple[Message, ...]
    limits: Limits | None = None
    temperature: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.tenant_id, str) or not self.tenant_id.strip():
            raise InvalidRequestError("tenant_id 必填且不能为空（宪法原则 V）")
        if not isinstance(self.model, str) or not self.model:
            raise InvalidRequestError("model 必填且不能为空")
        if not self.messages:
            raise InvalidRequestError("messages 至少需要 1 条")
        object.__setattr__(self, "messages", tuple(self.messages))
        if self.temperature is not None and not (0 <= self.temperature <= 2):
            raise InvalidRequestError(
                f"temperature 必须在 [0, 2] 区间，收到: {self.temperature!r}"
            )


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str
    usage: TokenUsage
    cost_usd: float
    finish_reason: str
