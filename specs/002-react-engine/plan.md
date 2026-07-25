# Implementation Plan: ReAct 引擎

**Branch**: `002-react-engine` | **Date**: 2026-07-25 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/002-react-engine/spec.md`

## Summary

在 `src/kernel/react/` 中实现完整的 ReAct 循环，替换 001 的
`SingleShotReactLoop` 占位实现，`ReactLoop` Protocol 签名不变。
每步驱动一次 `LLMProvider.complete()` 调用，用结构化 JSON 输出约定
判定"给出最终答案"还是"调用某个工具"；工具经 `Tool` Protocol 执行，
失败转为观察反馈进入下一轮；达到 `max_steps` 明确终止并返回类型化结果；
每步产生步数/工具标注的 OTel span，与 provider 自带 span 共同构成运行轨迹。
测试全部用 stub provider（可编程脚本化响应）与 stub tool 驱动，零外部依赖。

## Technical Context

**Language/Version**: Python 3.12（延续 001）

**Primary Dependencies**: 仅依赖内核自身（`kernel.provider`、`kernel.tool`）与
`opentelemetry-api`/`opentelemetry-sdk`（已是 001 依赖，无新增）

**Storage**: N/A（本 feature 无持久化；运行状态仅存活于单次调用的内存中）

**Testing**: pytest + pytest-asyncio；stub provider 用可编程脚本化的
`LLMProvider`（注入 `httpx.MockTransport`，按预设响应序列模拟"决定调用工具"
与"给出最终答案"两种输出）；stub tool 直接实现 `Tool` Protocol

**Target Platform**: 同 001（Linux server / 本地开发）

**Project Type**: library（内核子模块，延续 001 的单包结构）

**Performance Goals**: 引擎自身每步编排开销 <5ms（参考值，不作为验收标准、
不设基准测试任务——LLM 调用秒级耗时下编排开销非瓶颈，同 001 的处理方式）

**Constraints**: 不改变 001 冻结的 `ReactLoop` Protocol 签名；不引入新的限额概念
（复用 provider 已有超时/成本/token 上限）；不做重试；单步只调用一个工具

**Scale/Scope**: 约 4-5 个源文件 + 单元测试；不涉及平台层、不涉及沙箱（004 范围）

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 门禁检查 | 结果 |
|------|----------|------|
| I. 分层架构 | react 模块仅依赖 kernel.provider/kernel.tool（内核内部依赖），不 import 平台层 | ✅ 通过 |
| II. 最简实现 | 复用 provider 已有限额机制，不新增限额概念；不做重试；不支持并行多工具（范围收窄见 spec Assumptions） | ✅ 通过 |
| III. 组装优先 | 不引入任何新第三方组件，零新增依赖 | ✅ 通过 |
| IV. 超时与成本上限 | 每步的 LLM 调用经 provider 发起，自动继承其超时/token/成本上限；引擎自身不重复实现限额 | ✅ 通过 |
| V. OTel GenAI 可观测 | 每步产生步数/工具标注 span，provider 自带 span 天然携带 tenant_id；两者共同构成运行轨迹（FR-008） | ✅ 通过 |
| VI. 测试与安全边界 | max_steps 必填正整数、达到上限强制终止（FR-002/FR-006）；react 模块单元测试覆盖全部场景（FR-010） | ✅ 通过 |

**Post-Phase-1 re-check**: 设计产物未引入新依赖或新抽象，六项门禁维持通过。

## Project Structure

### Documentation (this feature)

```text
specs/002-react-engine/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── react-loop-api.md   # ReactLoop 对上层暴露的接口契约（复用 001 签名）
└── tasks.md             # Phase 2 output (/speckit-tasks - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/kernel/react/
├── __init__.py          # 导出 ReactLoop Protocol、ReactEngine（替换 SingleShotReactLoop）、结果类型
├── models.py             # StepRecord / Observation / ReactResult / StepBudgetExceededError
├── prompting.py          # 构造"思考"阶段的消息（含工具清单、历史步骤），解析结构化输出
├── telemetry.py          # 每步 span：步数、是否调用工具、工具名
└── engine.py             # ReactEngine：循环编排（思考→行动→观察→判断终止）

tests/unit/react/
├── conftest.py           # 脚本化 stub provider 工厂、stub tool 工厂
├── test_engine_answer.py       # US1：直接回答 / 工具调用后回答 / 未注册工具容错
├── test_engine_step_budget.py  # US2：步数耗尽类型化终止、max_steps 校验、边界 max_steps=1
├── test_engine_provider_errors.py  # Edge Case：provider 异常原样上抛，不被吞
└── test_engine_telemetry.py    # US3：步数/工具 span 标注、终止类型可区分、遥测容错、并发不串扰
```

**Structure Decision**: 延续 001 的单包 library 布局，`react` 子包内部按职责拆分
（数据结构/提示构造/遥测/编排循环各一文件），不新增顶层包。
