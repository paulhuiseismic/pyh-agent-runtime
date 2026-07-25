---

description: "Task list for ReAct 引擎"
---

# Tasks: ReAct 引擎

**Input**: Design documents from `/specs/002-react-engine/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md；
依赖 001（`kernel.provider`、`kernel.tool` 已交付）

**Tests**: 包含测试任务——宪法原则 VI 强制要求内核模块附带单元测试（FR-010），
不适用模板的"测试可选"约定。

**Organization**: 按用户故事分组；US1→US2→US3 在 `engine.py` 上有递进依赖
（同文件演进）。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无未完成依赖）
- **[Story]**: 所属用户故事（US1-US3）

## Path Conventions

延续 001 的单包 library 布局：`src/kernel/react/`、`tests/unit/react/`。

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 目录骨架，全部后续任务的前提

- [X] T001 创建目录骨架：tests/unit/react/ 目录、tests/unit/react/__init__.py

**Checkpoint**: `pytest tests/unit/react` 可运行（0 tests）

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 数据结构、异常与测试设施——所有用户故事的共同依赖

**⚠️ CRITICAL**: 本阶段完成前任何用户故事不能开工

- [X] T002 实现数据结构 src/kernel/react/models.py：frozen dataclass Observation（success/content）、
      StepRecord（index/action/tool_name/observation，内部使用）、
      StepBudgetExceededError（steps_executed/last_observation，非 ProviderError 层级）（data-model.md）
- [X] T003 [P] 实现思考阶段提示构造与解析 src/kernel/react/prompting.py：
      build_thought_messages(goal, tools, history) 构造含工具清单与历史步骤的消息列表、
      要求结构化 JSON 输出的 system 提示；parse_thought(content) 解析
      {"action": "final_answer"|"call_tool", ...} → action 为非法值或非 JSON 时返回 "malformed"（research.md R1）
- [X] T004 [P] 实现步骤遥测 src/kernel/react/telemetry.py：react_step_span(step_index, action, tool_name) 上下文管理器，
      span name="react.step"，属性 react.step.index/action/tool_name，复用 kernel.provider 的 tracer（research.md R5），
      遥测异常 try/except 不影响调用（沿用 001 telemetry 容错模式）
- [X] T005 [P] 创建测试公共设施 tests/unit/react/conftest.py：脚本化 stub provider 工厂
      （复用 001 httpx.MockTransport，按调用顺序返回预设 JSON 响应队列）、stub tool 工厂
      （StubTool 类，可配置返回值或抛异常）、price_table fixture（research.md R6）

**Checkpoint**: 数据结构与提示解析单元测试通过（`pytest tests/unit/react/test_models.py tests/unit/react/test_prompting.py` 全绿，此二测试文件随 T002/T003 一并编写)

- [X] T006 [P] models 与 prompting 单元测试 tests/unit/react/test_models.py, tests/unit/react/test_prompting.py：
      Observation/StepBudgetExceededError 构造正确；parse_thought 对合法 final_answer/call_tool JSON、
      非 JSON、缺 action 字段、非法 action 值均返回预期结果

---

## Phase 3: User Story 1 - 通过多轮思考与工具调用得出最终答案 (Priority: P1) 🎯 MVP

**Goal**: 思考-行动-观察循环编排；工具失败转为观察反馈，不中断循环

**Independent Test**: 脚本化 stub provider + stub tool 驱动一次完整运行，
验证最终答案与步骤序列符合预期，全程无平台组件、无真实模型

- [X] T007 [US1] 实现 ReactEngine 核心循环 src/kernel/react/engine.py：
      __init__(provider, tools, model, max_step_limits=None)；run(goal, *, tenant_id, max_steps) 的
      思考（调用 provider.complete）→ 解析 action → final_answer 直接返回 / call_tool 执行工具并生成 Observation /
      malformed 生成失败观察 → 观察加入下一轮思考上下文（状态机见 data-model.md）
- [X] T008 [US1] 在 src/kernel/react/engine.py 中实现工具执行与失败捕获：
      工具名未在 tools 注册 → Observation(success=False)；tool.invoke() 抛任意异常 → 捕获转 Observation(success=False)；
      正常返回 → Observation(success=True)（FR-004/FR-005，research.md R4）
- [X] T009 [US1] 包级导出 src/kernel/react/__init__.py：按 contracts/react-loop-api.md 导出 ReactEngine、
      Observation、StepBudgetExceededError；保留/替换 ReactLoop Protocol 定义（001 签名不变，移除 SingleShotReactLoop）
- [X] T010 [P] [US1] 直接回答场景单元测试 tests/unit/react/test_engine_answer.py：
      stub provider 首步即返回 final_answer → engine 不发起工具调用直接返回（验收场景 US1-2）
- [X] T011 [P] [US1] 工具调用场景单元测试 tests/unit/react/test_engine_answer.py（同文件追加）：
      stub provider 首步返回 call_tool、次步返回 final_answer，stub tool 返回固定观察 →
      engine 两步完成，返回值基于工具观察（验收场景 US1-1）
- [X] T012 [P] [US1] 未注册工具容错单元测试 tests/unit/react/test_engine_answer.py（同文件追加）：
      stub provider 决定调用未注册工具名 → 该步转为失败观察反馈、循环继续到下一步而非崩溃（验收场景 US1-3）

**Checkpoint**: US1 测试全绿——MVP 可演示（stub 下一次完整多步运行）

---

## Phase 4: User Story 2 - 达到最大步数时明确终止 (Priority: P2)

**Goal**: max_steps 强制校验与执行，步数耗尽返回类型化结果，不超步、不抛未分类异常

**Independent Test**: 永远决定调用工具的 stub provider 驱动运行，
设 max_steps=3，验证恰好执行 3 步后终止并返回 StepBudgetExceededError

- [X] T013 [US2] 在 src/kernel/react/engine.py 补全步数控制：run() 起始校验 max_steps 为正整数
      （非正整数/非整数 → 复用 kernel.provider.errors.InvalidRequestError，开始任何步骤前拒绝，FR-002）；
      循环内每步计数，到达 max_steps 仍未 final_answer → 抛 StepBudgetExceededError(steps_executed, last_observation)
      （FR-006，状态机见 data-model.md；步数计数规则见 research.md R2）
- [X] T014 [P] [US2] 步数耗尽单元测试 tests/unit/react/test_engine_step_budget.py：
      永远 call_tool 的 stub provider + max_steps=3 → 异常 steps_executed==3 且不超步（验收场景 US2-1，SC-002）
- [X] T015 [P] [US2] max_steps 校验单元测试 tests/unit/react/test_engine_step_budget.py（同文件追加）：
      max_steps=0/-1/1.5 均在发起任何调用前被拒绝为 InvalidRequestError（未触发任何 provider 调用，验收场景 US2-2）
- [X] T016 [P] [US2] 边界单元测试 tests/unit/react/test_engine_step_budget.py（同文件追加）：
      max_steps=1 且首步即 call_tool → 立即以 StepBudgetExceededError(steps_executed=1) 终止，不额外多跑一步
      （验收场景 US2-3）

**Checkpoint**: US1+US2 测试全绿——步数保护完整

---

## Phase 5: Edge Case - Provider 异常原样上抛（不属独立用户故事，但为 P2 强约束的边界）

- [X] T017 [P] provider 异常边界单元测试 tests/unit/react/test_engine_provider_errors.py：
      stub provider 配置为抛 CallTimeoutError/TokenLimitExceededError（复用 001 stub 机制）→
      run() 原样上抛该异常类型，不被吞成观察结果、不算作步数耗尽（FR-007，research.md R3）

**Checkpoint**: provider 异常与步数耗尽边界清晰可辨

---

## Phase 6: User Story 3 - 每次运行可按步骤与工具追溯 (Priority: P3)

**Goal**: 每步产生步数/工具标注的 span，与 provider 自带 span 构成父子关系

**Independent Test**: InMemorySpanExporter 采集一次含 2 次工具调用的运行，
断言 span 集合包含每步标注且可关联父子关系

- [X] T018 [US3] 在 src/kernel/react/engine.py 集成步骤遥测：每次循环迭代经 telemetry.react_step_span 包裹
      （在其上下文内发起 provider.complete 调用，使 chat {model} span 成为其子 span），
      终止于 StepBudgetExceededError 时最后一步 span 标记 ERROR（FR-008，data-model.md span 契约）
- [X] T019 [US3] 遥测单元测试 tests/unit/react/test_engine_telemetry.py：
      多步运行产生的 react.step span 数量与步数一致、属性含 index/action/tool_name、
      provider 调用 span 为其子 span（断言 chat span 的 parent.span_id == 对应 react.step span
      的 context.span_id，而非仅比对数量，见 research.md R5）（验收场景 US3-1）；
      步数耗尽运行的最后一步 span 标记 ERROR（验收场景 US3-2）；注入抛异常的 span 处理不影响
      运行结果（验收场景 US3-3，FR-009）；并发运行（含相同 tenant_id 的多次并发 run 与不同
      tenant_id 的并发 run 两种情形）的步数计数与 span 归属互不串扰（Edge Case）

**Checkpoint**: 全部用户故事测试独立全绿

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: 演示脚本、文档收尾与最终验证

- [X] T020 [P] 创建演示脚本 examples/demo_react_stub.py：脚本化 stub provider + stub tool + ConsoleSpanExporter，
      依次演示直接回答/工具调用后回答/步数耗尽三种运行并打印 span（quickstart.md 第 2 节的预期输出）
- [X] T021 按 quickstart.md 全流程验证：pytest tests/unit/react 全绿（SC-001）→ demo_react_stub 输出符合预期
      （SC-002/003/004）→ 计时确认 15 分钟内完成（SC-005），修复发现的问题
- [X] T022 更新 README.md roadmap：002 状态改为"已完成"

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 → Phase 2 → 用户故事**：严格顺序
- **US1 → US2 → Edge Case(Phase 5) → US3**：递进依赖（均在 engine.py 上演进：
  US1 建立核心循环，US2 补步数控制，US3 织入遥测；Phase 5 的异常边界测试依赖
  US1 的核心循环已存在，可与 US2 并行编写）
- **Phase 7**：依赖 US1-US3 全部完成

### Parallel Opportunities

- Phase 2 内：T003、T004、T005 并行（T002 先行，T006 随后）
- US1 内：T010/T011/T012 同文件但断言独立，编写时可并行准备后顺序追加
- 跨阶段：T017（Phase 5）可与 T013-T016（US2）并行编写
- Phase 7：T020 与 T021 顺序（T021 依赖 T020 产出的脚本）

## Implementation Strategy

**MVP = Phase 1 + 2 + US1**（T001-T012）：stub 下跑通一次完整多步运行
（含工具调用与失败容错）即可演示。随后 US2 → Edge Case → US3 递增交付。
每个 Checkpoint 处 `pytest` 必须全绿再前进。
