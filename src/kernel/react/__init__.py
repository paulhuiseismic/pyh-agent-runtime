"""kernel.react 公共接口（契约见 specs/002 contracts/react-loop-api.md）。

ReactLoop Protocol 签名冻结于 001，本 feature 不得修改。
"""

from typing import Protocol, runtime_checkable

from kernel.react.engine import ReactEngine
from kernel.react.models import Observation, StepBudgetExceededError


@runtime_checkable
class ReactLoop(Protocol):
    async def run(self, goal: str, *, tenant_id: str, max_steps: int) -> str: ...


__all__ = ["ReactLoop", "ReactEngine", "Observation", "StepBudgetExceededError"]
