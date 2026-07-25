"""react 数据结构：Observation / StepBudgetExceededError（见 specs/002 data-model.md）。

StepBudgetExceededError 不属于 kernel.provider.errors.ProviderError 层级——
步数耗尽与 provider 调用失败是两类不同的失败语义（research.md R3）。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Observation:
    success: bool
    content: str


class StepBudgetExceededError(Exception):
    def __init__(self, steps_executed: int, last_observation: str):
        self.steps_executed = steps_executed
        self.last_observation = last_observation
        super().__init__(
            f"达到步数上限（已执行 {steps_executed} 步）仍未得出最终答案，"
            f"最后观察: {last_observation}"
        )
