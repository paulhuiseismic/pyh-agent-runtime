"""memory 配置结构：ContextBudget（见 specs/003 data-model.md，research.md R4）。"""

from dataclasses import dataclass

from kernel.provider.errors import InvalidRequestError

DEFAULT_MAX_CONTEXT_TOKENS = 4000
DEFAULT_KEEP_RECENT_MESSAGES = 6


@dataclass(frozen=True)
class ContextBudget:
    max_context_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS
    keep_recent_messages: int = DEFAULT_KEEP_RECENT_MESSAGES

    def __post_init__(self) -> None:
        for name, value in (
            ("max_context_tokens", self.max_context_tokens),
            ("keep_recent_messages", self.keep_recent_messages),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise InvalidRequestError(
                    f"ContextBudget.{name} 必须是正整数（宪法：不允许'不压缩'为默认行为），"
                    f"收到: {value!r}"
                )
