# Contract: react 公共 Python 接口

**Consumer**: 平台层调度器（未来 feature 005）
**Provider**: `kernel.react`

数据结构见 [data-model.md](../data-model.md)。

## 公共导出（`kernel.react` 包级）

```python
from kernel.react import (
    ReactLoop,               # Protocol（001 已冻结，签名不变）
    ReactEngine,             # 完整实现，替换 SingleShotReactLoop
    Observation,
    StepBudgetExceededError,
)
```

## ReactEngine

```python
class ReactEngine:
    def __init__(
        self,
        *,
        provider: LLMProvider,   # 来自 kernel.provider，复用其超时/限额/span
        tools: dict[str, Tool],  # 来自 kernel.tool；key 为工具名
        model: str,               # 每步"思考"调用使用的模型（透传给 provider）
        max_step_limits: Limits | None = None,  # 每步调用的限额；None 用 provider 默认值
    ) -> None: ...

    async def run(self, goal: str, *, tenant_id: str, max_steps: int) -> str: ...
```

## 行为契约

1. `run()` 满足 001 冻结的 `ReactLoop` Protocol，可直接替换
   `SingleShotReactLoop` 用于任何已依赖该 Protocol 的调用方。
2. 成功返回最终答案字符串；失败分两类：
   - `StepBudgetExceededError`（本 feature 新增）：步数耗尽。
   - `kernel.provider.errors.ProviderError` 子类：某步的 LLM 调用本身失败，
     原样上抛（不是引擎包装的异常）。
   调用方 MUST 能通过 `except` 区分这两类失败并采取不同补救策略。
3. 工具执行失败（未注册/异常）不会导致 `run()` 抛异常，只会消耗一个步数
   并将失败信息带入下一轮思考——除非因此耗尽 max_steps，此时按上条第一类处理。
4. 每次 `run()` 调用（含因任何原因终止）产生完整的 span 轨迹：
   每步一条 `react.step` span，其内部 provider 调用产生的 `chat {model}`
   span 作为子 span 挂载。
5. 不修改 001 已冻结的 `kernel.provider` 与 `kernel.tool` 公共契约。

## 兼容性承诺

- `ReactEngine.__init__` 的参数只增不删；`run()` 签名冻结于 001，
  本 feature 不得修改（FR-011）。
- `StepBudgetExceededError` 字段只增不删。
