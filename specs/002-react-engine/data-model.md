# Data Model: ReAct 引擎

**Date**: 2026-07-25 | **Plan**: [plan.md](plan.md) | 决策依据见 [research.md](research.md)

结构定义于 `src/kernel/react/models.py`（frozen dataclass，风格延续 001）。

## Observation（观察结果）

| 字段 | 类型 | 说明 |
|------|------|------|
| success | bool | 工具是否成功执行（未注册/抛异常 → False） |
| content | str | 成功时为工具返回值；失败时为失败说明（供下一轮思考参考） |

## StepRecord（单步记录，内部状态，不对外暴露）

| 字段 | 类型 | 说明 |
|------|------|------|
| index | int | 步数序号，从 1 开始 |
| action | str | `final_answer` / `call_tool` / `malformed`（思考结果解析失败） |
| tool_name | str \| None | 仅 action=call_tool 时有值 |
| observation | Observation \| None | 仅 action=call_tool 时有值（malformed 步无观察，直接作为失败观察反馈） |

## StepBudgetExceededError（新增异常，定义于 models.py）

不属于 `kernel.provider.errors.ProviderError` 层级（二者语义不同，见 research.md R3）。

| 字段 | 类型 | 说明 |
|------|------|------|
| steps_executed | int | 实际执行的步数（等于 max_steps） |
| last_observation | str | 最后一次观察内容（若最后一步是 malformed，则为该次思考的原始输出摘要） |

## ReactRequest（运行入参，非 dataclass——对应 `ReactLoop.run()` 的参数）

延续 001 冻结的 `ReactLoop` Protocol 签名，不新增顶层数据结构：

```python
async def run(self, goal: str, *, tenant_id: str, max_steps: int) -> str: ...
```

工具集合通过 `ReactEngine.__init__(*, provider, tools)` 在构造时注入
（`tools: dict[str, Tool]`），不是 `run()` 的参数——因为 `ReactLoop.run()`
签名已在 001 冻结，不能新增参数；工具集合与 provider 一样属于引擎实例的
依赖，在构造引擎时确定。

## 思考阶段的结构化输出契约（prompting.py 内部约定，非公共契约）

LLM 响应内容（`LLMResponse.content`）应为以下两种 JSON 之一：

```json
{"action": "final_answer", "content": "<最终答案文本>"}
```

```json
{"action": "call_tool", "tool": "<已注册工具名>", "arguments": {"...": "..."}}
```

解析规则：非 JSON、缺 `action`、`action` 不属于上述两值 → 记为
`action="malformed"`，`content` 取原始响应文本前 200 字符作为失败观察反馈
（不是抛异常，视为"这一步没有产出有效行动"，消耗一个步数，见 research.md R1）。

## 状态流转（一次运行）

```text
run(goal, tenant_id, max_steps)
  → 校验 max_steps > 0 且为整数 ──否→ InvalidRequestError（复用 001 异常，发出前拒绝）
  → 校验 goal / tenant_id 非空 ──否→ InvalidRequestError
  → step = 1
  → loop:
      思考：调用 provider.complete(...) 生成本步决策
        ├─ ProviderError 子类 ──→ 原样上抛，运行终止（R3）
      解析决策 → action ∈ {final_answer, call_tool, malformed}
      记录 react.step span（step index, action, tool_name?）
      若 action == final_answer → 返回 content，运行成功结束
      若 action == call_tool:
          执行 tool.invoke(arguments, tenant_id=tenant_id)
            ├─ 未注册/异常 ──→ Observation(success=False, content=<说明>)
            └─ 成功 ──→ Observation(success=True, content=<返回值>)
          将 Observation 加入下一轮思考的上下文
      若 action == malformed:
          将原始输出前 200 字符作为失败观察加入下一轮思考的上下文
      若 step == max_steps → 抛 StepBudgetExceededError(steps_executed=step,
          last_observation=<本步观察或 malformed 摘要>)，运行终止
      step += 1
```

## 遥测 span 契约（`react.step`，见 research.md R5）

| 属性 | 值 |
|------|-----|
| span name | `react.step` |
| `react.step.index` | 当前步数（从 1 开始） |
| `react.step.action` | `final_answer` / `call_tool` / `malformed` |
| `react.step.tool_name` | 仅 call_tool 时存在 |
| 父子关系 | 该步内 provider 调用的 `chat {model}` span 是其子 span |
| span status | 正常完成/终止 OK；因 `StepBudgetExceededError` 终止的最后一步 ERROR |
