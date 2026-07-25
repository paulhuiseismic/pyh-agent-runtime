---

description: "Task list for 内核骨架与 provider 模块"
---

# Tasks: 内核骨架与 provider 模块

**Input**: Design documents from `/specs/001-kernel-provider/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: 包含测试任务——宪法原则 VI 强制要求内核模块附带单元测试（FR-009），
不适用模板的"测试可选"约定。

**Organization**: 按用户故事分组；US1→US2→US3 在 `client.py` 上有递进依赖
（同文件演进），US4 完全独立可并行。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无未完成依赖）
- **[Story]**: 所属用户故事（US1-US4）

## Path Conventions

单包 library 布局（src layout）：`src/kernel/`、`tests/unit/`，见 plan.md 结构决策。

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 包定义与目录骨架，全部后续任务的前提

- [ ] T001 创建 pyproject.toml：包名 kernel（src layout）、Python 3.12、依赖 httpx + opentelemetry-sdk + opentelemetry-api，dev 依赖 pytest + pytest-asyncio，pytest 配置（asyncio_mode=auto）
- [ ] T002 创建包目录骨架与空 `__init__.py`：src/kernel/__init__.py、src/kernel/provider/__init__.py、src/kernel/react/__init__.py、src/kernel/memory/__init__.py、src/kernel/tool/__init__.py、tests/unit/provider/ 目录
- [ ] T003 [P] 创建 THIRD_PARTY.md：登记 LiteLLM（MIT，仅核心功能，不使用 enterprise 目录功能）、httpx（BSD-3）、OpenTelemetry Python（Apache-2.0）（FR-010）

**Checkpoint**: `pip install -e ".[dev]"` 成功，`pytest` 可运行（0 tests）

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 数据结构与异常层级——所有用户故事的共同依赖

**⚠️ CRITICAL**: 本阶段完成前任何用户故事不能开工

- [ ] T004 实现数据结构 src/kernel/provider/models.py：frozen dataclass Message / Limits（默认 60.0s / 8192 / 0.50）/ ModelPrice / PriceTable / LLMRequest / TokenUsage / LLMResponse，含各自校验函数（正数、非空、role 枚举；规则见 data-model.md）
- [ ] T005 [P] 实现异常层级 src/kernel/provider/errors.py：ProviderError + 6 子类（InvalidRequestError / CallTimeoutError / TokenLimitExceededError / CostLimitExceededError / ProxyConnectionError / MalformedResponseError），超限类必须携带实际值与上限值字段（FR-005）
- [ ] T006 [P] 创建测试公共设施 tests/unit/provider/conftest.py：httpx.MockTransport 响应工厂（成功响应/慢响应/畸形响应/连接异常/自定义 usage），OTel TracerProvider + InMemorySpanExporter fixture，默认 PriceTable fixture
- [ ] T007 models 校验单元测试 tests/unit/provider/test_models.py：合法构造、非法限额（0/负数/NaN/inf）、空消息列表、非法 role 均按规则拒绝

**Checkpoint**: `pytest tests/unit/provider/test_models.py` 全绿

---

## Phase 3: User Story 1 - 通过 provider 完成一次受保护的 LLM 调用 (Priority: P1) 🎯 MVP

**Goal**: 统一请求经 proxy 契约完成调用，返回统一响应（内容/用量/成本）

**Independent Test**: MockTransport 模拟 proxy，构造请求调用 `complete()`，
断言响应结构完整，全程无平台组件、无真实密钥

- [ ] T008 [US1] 实现成本计算 src/kernel/provider/pricing.py：estimate_input_tokens（字符数/4 粗估；代码注释记录已知偏差——对中文等非拉丁文本严重低估 token 数，会高估剩余输出预算，由响应侧校验兜底）、calculate_cost（PriceTable × TokenUsage，单价缺失抛 InvalidRequestError）（research.md R8/R9）
- [ ] T009 [US1] 实现 LLMProvider 成功路径 src/kernel/provider/client.py：构造器（base_url/price_table/api_key/default_limits/transport 注入）、complete() 的校验链（请求结构→tenant_id→limits→单价→输入粗估）与 POST /v1/chat/completions（显式 timeout、max_tokens=剩余预算、stream=false）、响应解析为 LLMResponse、aclose()（契约见 contracts/provider-api.md 与 contracts/litellm-proxy-contract.md）
- [ ] T010 [US1] 包级导出 src/kernel/provider/__init__.py：按 contracts/provider-api.md 导出 LLMProvider、全部数据结构与异常
- [ ] T011 [P] [US1] 成功调用单元测试 tests/unit/provider/test_client_success.py：统一响应字段完整（content/model/usage/cost_usd/finish_reason）、模型名透传与响应模型回读、温度参数按需传递、成本计算正确（验收场景 US1-1/2）
- [ ] T012 [P] [US1] 参数校验单元测试 tests/unit/provider/test_client_validation.py：缺/空 tenant_id 在发出前拒绝且不产生 HTTP 请求、非法限额拒绝、模型无单价拒绝、空消息拒绝（验收场景 US1-3，边界：非法限额/无单价）

**Checkpoint**: US1 测试全绿——MVP 可演示（stub 下一次完整调用）

---

## Phase 4: User Story 2 - 超时与超限调用明确失败 (Priority: P2)

**Goal**: 超时/token/成本三类超限返回类型化失败，默认值安全，绝不静默

**Independent Test**: MockTransport 模拟慢响应/超长 usage/高成本响应，
分别断言三类异常及其携带的实际值与上限值

- [ ] T013 [US2] 在 src/kernel/provider/client.py 补全限额执行：httpx.TimeoutException→CallTimeoutError、响应侧 usage 校验超限→TokenLimitExceededError、成本校验超限→CostLimitExceededError、未指定 limits 时套用 default_limits（FR-004/FR-005，状态机见 data-model.md）
- [ ] T014 [US2] 在 src/kernel/provider/client.py 补全错误映射：连接失败/DNS/HTTP 4xx-5xx→ProxyConnectionError（含状态码与响应体摘要，不重试）、JSON 非法或缺必要字段→MalformedResponseError（错误映射表见 contracts/litellm-proxy-contract.md）
- [ ] T015 [P] [US2] 限额单元测试 tests/unit/provider/test_client_limits.py：慢响应在设定超时的 1.5 倍时间内终止并抛 CallTimeoutError（口径对齐 SC-003）、token 超限异常含实际/上限值、成本超限异常含实际/上限值、缺省 limits 采用安全默认值、输入粗估超预算发出前拒绝（验收场景 US2-1/2/3/4）
- [ ] T016 [P] [US2] 错误映射单元测试 tests/unit/provider/test_client_errors.py：连接拒绝抛 ProxyConnectionError 且不重试、HTTP 500 映射、畸形响应（缺 usage/缺 choices/非 JSON）抛 MalformedResponseError（边界场景）

**Checkpoint**: US1+US2 测试全绿——调用能力带完整保护

---

## Phase 5: User Story 3 - 每次调用可按租户追溯 (Priority: P3)

**Goal**: 每次调用（含失败）发出 GenAI 语义 span，`tenant_id` 必带，遥测失败不伤调用

**Independent Test**: InMemorySpanExporter 采集成功/超时/超限三种调用，
断言 span 数量与属性契约

- [ ] T017 [US3] 实现遥测模块 src/kernel/provider/telemetry.py：span 命名 `chat {model}`、GenAI 属性集 + tenant_id（属性契约见 data-model.md）、失败路径 status=ERROR + 异常类名、tenant_id 缺失时以 "<missing>" 占位、整体 try/except 包裹（遥测异常仅记 warning 日志，FR-006/FR-007）
- [ ] T018 [US3] 在 src/kernel/provider/client.py 集成遥测：complete() 全路径（成功/全部异常/发出前拒绝）经 telemetry 发出 span，确保 finally 语义
- [ ] T019 [US3] 遥测单元测试 tests/unit/provider/test_telemetry.py：成功调用 span 属性齐全（tenant_id/gen_ai.request.model/usage/cost）、超时与超限调用 span status=ERROR 且注明异常类型、发出前拒绝也有 span、注入抛异常的 exporter 验证调用结果不受影响、并发调用互不串扰（同一并发用例同时断言：各调用 span 归属正确、各自的超时/限额结果互不影响）（验收场景 US3-1/2/3，SC-002，边界：并发互不串扰）

**Checkpoint**: US1-US3 测试全绿——provider 完整交付

---

## Phase 6: User Story 4 - 内核骨架可独立演进 (Priority: P4)

**Goal**: react/memory/tool 接口（Protocol）+ 占位实现，零平台依赖

**Independent Test**: 干净环境运行全部单测通过，无网络、无平台组件

- [ ] T020 [P] [US4] 实现 react 接口 src/kernel/react/__init__.py：ReactLoop Protocol（async run(goal, *, tenant_id, max_steps)，max_steps 必填>0）+ SingleShotReactLoop 占位实现（签名见 data-model.md 骨架接口节）
- [ ] T021 [P] [US4] 实现 memory 接口 src/kernel/memory/__init__.py：Memory Protocol（load/append，均必带 tenant_id）+ NoopMemory 占位实现
- [ ] T022 [P] [US4] 实现 tool 接口 src/kernel/tool/__init__.py：Tool Protocol（name/description/invoke(arguments, *, tenant_id)）+ EchoTool 占位实现（不含沙箱语义，沙箱属 feature 004）
- [ ] T023 [US4] 骨架单元测试 tests/unit/test_kernel_skeleton.py：四模块可导入与实例化、占位实现满足各自 Protocol（isinstance 结构检查）、max_steps≤0 拒绝、静态断言 kernel 包内无平台层 import（遍历 kernel 源文件检查 import 语句，SC-005）

**Checkpoint**: 全部用户故事测试独立全绿

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: 演示脚本、文档收尾与最终验证

- [ ] T024 [P] 创建演示脚本 examples/demo_stub.py：MockTransport + ConsoleSpanExporter，依次演示成功调用/超时失败/成本超限失败并打印 span（quickstart.md 第 2 节的预期输出）
- [ ] T025 [P] 创建真实 proxy 演示脚本 examples/demo_proxy.py：base_url 指向 http://localhost:4000，行为与 demo_stub 一致（quickstart.md 第 3 节，可选运行）
- [ ] T026 按 quickstart.md 全流程验证：干净 venv 安装 → pytest 全绿（SC-001）→ demo_stub 输出符合预期（SC-002/003）→ 计时确认 15 分钟内完成（SC-004），修复发现的问题
- [ ] T027 更新 README.md roadmap：001 状态改为"已完成"

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 → Phase 2 → 用户故事**：严格顺序
- **US1 → US2 → US3**：递进依赖（三者都在 client.py 上演进，US2 补全 US1 的失败路径，US3 织入遥测）
- **US4**：仅依赖 Phase 1，可与 US1-US3 全程并行
- **Phase 7**：依赖 US1-US4 全部完成

### Parallel Opportunities

- Phase 1 内：T003 与 T001/T002 并行
- Phase 2 内：T005、T006 并行（T004 先行，T007 随后）
- 各故事内：测试任务两两并行（T011‖T12、T015‖T016）
- 跨故事：T020/T021/T022（US4）随时可与 US1-US3 并行
- Phase 7：T024‖T025

## Implementation Strategy

**MVP = Phase 1 + 2 + US1**（T001-T012）：stub 下跑通一次完整受保护调用即可演示。
随后按 US2 → US3 递增交付；US4 可穿插任意空档。每个 Checkpoint 处 `pytest` 必须全绿再前进。
