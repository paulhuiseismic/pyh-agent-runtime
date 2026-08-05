---

description: "Task list for 平台服务层 + web service（REST API）"
---

# Tasks: 平台服务层 + web service（REST API）

**Input**: Design documents from `/specs/007-platform-web-service/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md；
依赖 001（`LLMProvider`）、002（`ReactEngine`）、003（`SqliteMemory`）、004
（`LongTermMemory`）、005/006（`ToolRegistry`，含沙箱工具与 MCP 工具）

**Tests**: 包含测试任务——宪法原则 VI 强制要求新增模块附带单元测试。全部测试
均可在无外部网络、无真实模型密钥的情况下运行（内核调用复用 001 已确立的
`httpx.MockTransport` stub 模式，HTTP 层用 `httpx.ASGITransport` 内存直调）。

**Organization**: 按用户故事分组；US1（REST 调用入口）是 MVP 且独立可测；
US2（并发调度、请求超时与同会话串行化）在 US1 建立的 `app.py`/
`agent_service.py` 上补充资源保护；US3（租户识别与遥测贯通）补全
`platform.request` span 与"未识别租户先于内核调用被拒绝"的显式验证。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无未完成依赖）
- **[Story]**: 所属用户故事（US1-US3）

## Path Conventions

新增独立顶层包：`src/platform_service/`、`tests/unit/platform_service/`
（延续 001-006 的单包 library 布局风格，见 plan.md Structure Decision）。

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 引入新依赖、登记 license、准备包与测试目录骨架

- [X] T001 在 pyproject.toml 的 `dependencies` 中新增 `fastapi`，并把已在
      依赖树中的 `uvicorn` 提升为直接依赖；在 THIRD_PARTY.md 追加两行登记
      （组件名/MIT license/Python 库依赖/无特殊约束），随后执行
      `pip install -e ".[dev]"` 验证安装成功
- [X] T002 [P] 创建包骨架 src/platform_service/__init__.py（暂为空模块，
      导出留待 T014 补全）
- [X] T003 [P] 创建测试目录骨架 tests/unit/platform_service/__init__.py

**Checkpoint**: `python -c "import platform_service"` 可正常导入

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 配置结构、异常层级、数据模型、测试设施——所有用户故事的共同依赖

**⚠️ CRITICAL**: 本阶段完成前任何用户故事不能开工

- [X] T004 实现配置 src/platform_service/config.py：frozen dataclass
      `TenantConfig`（api_key/tenant_id/max_concurrent_requests，正整数
      校验）、`PlatformConfig`——
      `tenants`/`global_max_concurrent_requests`/`request_timeout_seconds`/
      `model`/`max_steps`（均正数校验，`api_key`/`tenant_id` 不允许重复）+
      **`provider_base_url: str`（必填，非空）**、
      **`provider_api_key: str | None`**、
      **`price_table: kernel.provider.models.PriceTable`（必填，MUST 包含
      `model` 对应的单价，否则构造时抛异常）**、
      **`provider_call_limits: kernel.provider.models.Limits | None`**、
      **`mcp_servers: list[kernel.tool.McpServerConfig]`（默认空列表）**
      （FR-013/FR-014，data-model.md）；任一校验失败抛 `InvalidRequestError`
      （复用 001 异常）——**这是 C1/C2 修正项：没有这些字段
      `AgentService` 将无法构造出可用的 `LLMProvider`/`ToolRegistry`**
- [X] T005 [P] 实现平台层异常 src/platform_service/errors.py：
      `AuthenticationError(detail)`、
      `ConcurrencyLimitExceededError(scope: "tenant"|"global")`、
      `RequestTimeoutError(timeout_seconds)`（均独立于内核异常层级，
      data-model.md）
- [X] T006 [P] 实现数据模型 src/platform_service/models.py：pydantic
      `AgentRunRequest`（goal: str 非空必填，session_id: str|None）、
      `AgentRunResult`（status/answer/session_id）
- [X] T007 [P] 创建测试公共设施 tests/unit/platform_service/conftest.py：
      示例 `PlatformConfig`/`TenantConfig` fixture（含至少两个租户，便于
      US2 的租户间隔离测试；`provider_base_url`/`price_table` 均填好合法
      占位值）、stub `LLMProvider` fixture（复用 001 `httpx.MockTransport`
      模式，返回固定的 ReAct `final_answer` JSON，并提供一个"慢响应"变体
      供 US2 的并发/超时测试使用）
- [X] T008 [P] 配置与异常单元测试
      tests/unit/platform_service/test_config.py：默认值/正常构造成功；
      并发上限/超时字段 ≤0、重复 api_key/tenant_id、`provider_base_url`
      为空、`price_table` 未覆盖 `model` 对应单价，均抛
      `InvalidRequestError`（C1/C2 修正项覆盖）；三类平台异常的诊断字段
      可正确构造与读取

**Checkpoint**: `pytest tests/unit/platform_service/test_config.py` 全绿

---

## Phase 3: User Story 1 - 通过 REST API 发起一次 agent 调用并获得结果 (Priority: P1) 🎯 MVP

**Goal**: 外部调用方携带租户标识和问题发起 REST 请求，无需了解内部内核
能力组合即可获得最终结果；未识别出租户/内核调用失败均有明确响应

**Independent Test**: 用 stub provider 驱动，发起一次合法请求验证成功
响应；发起一次不带 API Key 的请求验证鉴权失败响应；模拟内核调用失败
验证对应失败响应——全程不依赖 US2 的并发调度、US3 的遥测断言

- [X] T009 [US1] 实现鉴权 src/platform_service/auth.py：
      `resolve_tenant(api_key, config) -> str`，未匹配到任何
      `TenantConfig.api_key` 时抛 `AuthenticationError`（FR-002）
- [X] T010 [US1] 实现核心服务 src/platform_service/agent_service.py：
      `AgentService.__init__(provider, tool_registry, session_memory,
      long_term_memory, config)`；`handle(request, *, tenant_id)`——
      按 data-model.md 序列：查询长期记忆事实（如有）→ 加载会话历史
      （如提供 session_id）→ 拼接为单一 `goal` 字符串 → 构造
      `ReactEngine(provider=..., tools=tool_registry.as_dict(), model=
      config.model)` 并 `await engine.run(拼接后的 goal, tenant_id=
      tenant_id, max_steps=config.max_steps)` → 成功后把用户问题与最终
      答案写回会话记忆（如提供 session_id）→ best-effort 提炼长期记忆
      （失败不影响返回）→ 返回 `AgentRunResult(status="success", ...)`；
      内核抛出的任何异常直接向上传播，不在此处捕获（research.md R3）；
      本任务暂不含会话级串行化（FR-015 留待 US2 的 T018 补全）
- [X] T011 [US1] 实现 FastAPI 应用 src/platform_service/app.py：
      应用启动（lifespan）时用 `PlatformConfig.provider_base_url`/
      `provider_api_key`/`price_table`/`provider_call_limits` 构造一次
      共享的 `LLMProvider`（001），用 `PlatformConfig.mcp_servers` 依次
      `connect()`/`register_mcp_tools()` 构建共享 `ToolRegistry`（005/006，
      research.md R4；空列表时 `ToolRegistry` 允许为空），并构建
      `SqliteMemory`/`LongTermMemory`/`AgentService`；`POST /v1/agent/run`
      端点——读取 `X-API-Key` 请求头 → `auth.resolve_tenant` （失败映射
      401）→ 请求体由 FastAPI/pydantic 自动校验 `AgentRunRequest`（失败
      自动映射 422）→ `await agent_service.handle(request, tenant_id=
      tenant_id)` → 内核异常映射 502 → 成功返回 `AgentRunResult` 映射
      200（本任务暂不含并发调度与整体超时包裹，US2 补全）
- [X] T012 [US1] 包级导出 src/platform_service/__init__.py 追加：按
      contracts/agent-run-api.md 导出 `AgentService`、`AgentRunRequest`、
      `AgentRunResult`、`PlatformConfig`、`TenantConfig`、平台异常层级、
      FastAPI `app` 实例
- [X] T013 [P] [US1] 鉴权单元测试 tests/unit/platform_service/test_auth.py：
      合法 API Key 解析出正确 tenant_id（验收场景 US3-2 的前置）；未匹配
      的 API Key 抛 `AuthenticationError`（验收场景 US3-1 的前置）
- [X] T014 [P] [US1] AgentService 端到端单元测试
      tests/unit/platform_service/test_agent_service.py：stub provider +
      内存 `ToolRegistry` 驱动 `handle()`，验证返回
      `AgentRunResult(status="success", answer=...)`（验收场景 US1-1）；
      提供 session_id 时验证会话记忆中写入了用户问题与最终答案两条消息
      （验收场景 US1-3）；provider 抛出的异常经 `handle()` 原样向上传播
      （验收场景 US1-2 的前置）
- [X] T015 [P] [US1] FastAPI 端到端单元测试
      tests/unit/platform_service/test_app.py：用
      `httpx.AsyncClient(transport=httpx.ASGITransport(app=app))` 驱动——
      合法请求返回 200 且 `answer` 非空（验收场景 US1-1）；缺失/非法
      API Key 返回 401（验收场景 US3-1）；请求体缺少 `goal` 返回 422；
      内核调用失败（stub provider 配置为抛错）返回 502（验收场景 US1-2）

**Checkpoint**: US1 测试全绿——MVP 可演示（REST 请求 → AgentService 组合
内核能力 → 返回结果的完整闭环，含基本失败分类）

---

## Phase 4: User Story 2 - 运行调度与并发控制保护共享资源 (Priority: P2)

**Goal**: 单租户/全局并发上限触达时立即拒绝新请求，不影响其他租户；
单次请求整体处理有显式超时；同一会话标识下的并发请求被正确串行化

**Independent Test**: 配置一个很小的并发上限，并发发起超过上限数量的
请求，验证超出上限的请求得到明确拒绝且不影响其他租户；配置一个很短的
请求超时，验证长耗时请求被正确终止并返回超时响应；对同一 session_id
并发发起两个请求，验证两次写入的会话历史未交叉损坏

- [X] T016 [US2] 实现并发调度器 src/platform_service/scheduler.py：
      `ConcurrencyScheduler(config)`——`try_acquire(tenant_id)` 用
      `asyncio.Lock` 保护"检查上限+自增"的原子性，租户或全局任一超限时
      抛 `ConcurrencyLimitExceededError(scope=...)`，不阻塞等待
      （research.md R2，FR-012）；`release(tenant_id)` 对应自减，
      MUST NOT 抛异常
- [X] T017 [US2] 在 src/platform_service/app.py 集成调度与超时：
      鉴权成功后先 `scheduler.try_acquire(tenant_id)`（失败映射 429）；
      用 `asyncio.wait_for(agent_service.handle(...), timeout=
      config.request_timeout_seconds)` 包裹核心调用（超时映射 504，
      research.md R5）；`finally` 块调用 `scheduler.release(tenant_id)`
      确保计数器不泄漏
- [X] T018 [US2] 在 src/platform_service/agent_service.py 补全会话级
      串行化（C4 修正项，FR-015）：新增 `SessionLockRegistry`——按
      `session_id` 惰性创建/复用 `asyncio.Lock`（`dict[str, asyncio.Lock]`）；
      `AgentService.handle()` 在提供了 `session_id` 时，把"加载历史 → 拼接
      goal → 运行 ReAct → 写回历史"整段包裹在对应锁内（`finally` 释放）；
      未提供 `session_id` 的请求不加锁，不同 `session_id` 之间不互相阻塞
      （data-model.md SessionLockRegistry）
- [X] T019 [P] [US2] 并发调度器单元测试
      tests/unit/platform_service/test_scheduler.py：租户达到
      `max_concurrent_requests` 后再次 `try_acquire` 抛
      `ConcurrencyLimitExceededError(scope="tenant")`（验收场景 US2-1）；
      全局达到 `global_max_concurrent_requests` 后同样抛出
      `scope="global"`（验收场景 US2-2）；租户 A 超限不影响租户 B 的
      `try_acquire` 成功（验收场景 US2-3）；`release` 后计数正确回落，
      可再次 `try_acquire` 成功
- [X] T020 [P] [US2] 并发与超时的 FastAPI 端到端单元测试
      tests/unit/platform_service/test_app_scheduling.py：用一个并发上限
      为 1 的租户配置，并发发起 2 个请求（第二个用尚未完成的慢 stub
      provider 阻塞第一个），验证第二个请求收到 429（验收场景 US2-1）；
      用极短的 `request_timeout_seconds` 配合慢 stub provider，验证请求
      收到 504（FR-009）
- [X] T021 [P] [US2] 会话串行化单元测试
      tests/unit/platform_service/test_session_lock.py：对同一
      `session_id` 并发调用两次 `AgentService.handle()`（第二次在第一次
      的 stub provider 响应尚未返回时发起），验证两次写入会话记忆的历史
      消息总数正确（4 条：两轮各自的 user+assistant），且没有交叉/覆盖
      写入（FR-015，spec Edge Case）；对两个不同的 `session_id` 并发调用
      验证互不阻塞（各自尽快完成，不等待对方）

**Checkpoint**: US1+US2 测试全绿——资源保护完整，MVP 可在多租户并发场景
下安全运行，同会话并发请求不产生历史损坏

---

## Phase 5: User Story 3 - 请求被正确识别租户并与内核遥测打通 (Priority: P3)

**Goal**: 每个请求触发的全部内核可观测记录都携带一致的租户标识；未携带
合法租户标识的请求在触发任何内核调用之前即被拒绝

**Independent Test**: 发起一次成功请求后检查其触发的全部 span（含
`platform.request` 根 span 与内核的 `chat {model}`/`react.step` 等子
span），验证租户标识一致且父子关系正确；发起一次无租户标识的请求，验证
除鉴权失败本身外没有任何内核 span 被产生

- [X] T022 [US3] 扩展遥测 src/platform_service/telemetry.py：
      `platform_request_span(tenant_id, session_id)` 上下文管理器，
      span name="platform.request"，复用 kernel.provider 的 tracer
      （与 001-006 一致的 tracer 复用惯例），可后补 `result` 属性，
      遥测异常 try/except 不影响请求处理（data-model.md span 契约）
- [X] T023 [US3] 在 src/platform_service/app.py 集成 `platform_request_span`
      包裹整个端点处理逻辑（鉴权解析出 tenant_id 之后开始计入 span，
      鉴权失败前的拒绝不产生此 span 或以匿名/无 tenant_id 状态提前
      ERROR 结束，data-model.md），各失败类型对应设置 `result`
      （success/auth_failed/concurrency_exceeded/validation_failed/
      kernel_error/timeout）
- [X] T024 [P] [US3] 遥测与租户贯通单元测试
      tests/unit/platform_service/test_telemetry.py：用 in-memory span
      exporter 驱动一次成功请求，断言 `platform.request` span 与其触发
      的内核 `chat {model}` 子 span 均携带一致的 `tenant_id`，且子 span
      的 `parent.span_id == platform.request span 的 span_id`（复用
      001-006 已确立的父子 span 断言风格，不仅靠数量匹配，SC-005）；
      未携带合法 API Key 的请求验证不产生任何内核 span（只有鉴权失败
      本身的记录，US3 验收场景 1）

**Checkpoint**: US1-US3 测试全绿——REST 入口的租户识别、调度保护、
可观测性全部具备

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 示例配置、演示脚本、文档收尾与最终验证

- [ ] T025 [P] 创建示例配置 examples/platform_config.example.json：
      至少两个租户（不同 `max_concurrent_requests`）、一个全局并发上限、
      一个请求超时、`model`/`max_steps` 默认值、占位的
      `provider_base_url`/`price_table`（demo 脚本中会替换为 stub
      provider，示例文件本身仅用于展示完整字段结构），供 quickstart.md
      与 demo 脚本使用
- [ ] T026 [P] 创建演示脚本 examples/demo_platform_service.py：加载
      T025 的示例配置结构（provider 替换为 stub，避免需要真实模型密钥）、
      构建 FastAPI app、用 `httpx.ASGITransport` 依次演示成功调用、
      鉴权失败、并发超限、内核失败四个场景，并打印每次请求的
      `platform.request` span
- [ ] T027 按 quickstart.md 全流程验证：`pytest tests/unit/platform_service
      -v` 全绿（SC-001~SC-005、SC-007）→ demo 脚本输出符合预期 → 计时
      确认 15 分钟内完成，修复发现的问题
- [ ] T028 更新 README.md roadmap：007 状态改为"已完成"；更新
      examples/README.md 追加 `demo_platform_service.py` 条目

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 → Phase 2 → 用户故事**：严格顺序
- **US1**：依赖 Phase 2 全部任务，是 US2/US3 的基础（`app.py`/
  `AgentService` 均在 US1 建立）
- **US2**：依赖 US1 的 `app.py`/`agent_service.py` 骨架，在其上补充调度、
  超时与会话级串行化，不改动鉴权逻辑
- **US3**：依赖 US1 的 `app.py`/`AgentService`（用于验证 tenant_id 贯穿）
  与 US2 已建立的请求处理路径（遥测 span 需要包裹完整的处理流程，含
  调度判定），故排在 US2 之后实现，但其"未识别租户不触发内核调用"的
  核心断言在 US1 阶段已具备（US3 只是补充显式验证与 span 属性）
- **Phase 6**：依赖 US1-US3 全部完成

### Parallel Opportunities

- Phase 1 内：T002/T003 并行
- Phase 2 内：T005/T006/T007/T008 并行（T004 先行，T008 依赖 T004/T005 的类型定义）
- US1 内：T009 与 T010 可并行准备（互不依赖）；T011 依赖 T009/T010；
  T013/T014/T015 三个测试文件可并行编写
- US2 内：T019 依赖 T016；T020 依赖 T017；T021 依赖 T018；T019/T020/T021
  可并行编写（不同文件）
- US3 内：T023 依赖 T022；T024 依赖 T023
- Phase 6：T025/T026 可并行，T027 依赖 T026，T028 依赖 T027

## Implementation Strategy

**MVP = Phase 1 + 2 + US1**（T001-T015）：REST 请求 → 组合内核能力 → 返回
结果的完整闭环即可演示核心价值，且完全不需要并发调度、会话串行化或遥测
验证通过。随后 US2（并发/超时/会话串行化保护）→ US3（遥测贯通）递增交付，
最后 Polish 补齐示例配置、演示脚本与文档。每个 Checkpoint 处 `pytest`
必须全绿再前进。
