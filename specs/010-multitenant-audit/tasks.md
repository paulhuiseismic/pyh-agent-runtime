---

description: "Task list for 多租户强化与审计"
---

# Tasks: 多租户强化与审计

**Input**: Design documents from `/specs/010-multitenant-audit/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/,
quickstart.md；依赖 007（`app.py`/`AgentService`）、008（`cli.py`）、009
（`message_gateway.py`）——三者均需最小化扩展以补充审计记录来源

**Tests**: 包含测试任务——宪法附加约束要求平台层新增代码附带单元测试。
全部测试均可在无外部网络、无真实模型密钥的情况下运行（复用 001 已
确立的 `httpx.MockTransport` stub 模式；`AuditStore` 用真实临时
SQLite 文件驱动，同 003/004 既有测试风格）。

**Organization**: 按用户故事分组；US1（审计记录，MVP）建立
`AuditStore` 与 `AgentService` 的集成，是 US2/US3 的数据基础；US2
（查询汇总）在 US1 产生的数据之上补充只读查询能力；US3（配额强化）
复用 US1/US2 的同一份数据做前置校验，不引入第二套统计口径（FR-008）。

> **`/speckit-analyze` 修正说明**：初版 T015 的配额检查只是一次无
> 同步保护的"读取累计成本→比较"，同一租户并发发起多个请求会全部
> 放行、导致明显超额（F1，HIGH）；已改为用 `QuotaLockRegistry`
> （按 `tenant_id`）把"检查 → 内核调用 → 审计写入"整段串行化，见
> T015 与 research.md R6。另补充了 T019 的口径一致性回归测试
> （F2，MEDIUM），验证配额检查与查询端点确实共享同一份数据。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无未完成依赖）
- **[Story]**: 所属用户故事（US1-US3）

## Path Conventions

不新建顶层包——新增文件落入既有 `src/platform_service/`（新增
`audit.py`，扩展 `config.py`/`errors.py`/`agent_service.py`/`app.py`/
`cli.py`/`message_gateway.py`/`__init__.py`）与
`tests/unit/platform_service/`（新增 `test_audit.py`/
`test_app_audit.py`），见 plan.md Structure Decision。

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 测试公共设施准备（无新增第三方依赖）

- [X] T001 [P] 扩展 tests/unit/platform_service/conftest.py：新增
      `audit_store` fixture（临时文件路径构造的 `AuditStore`，测试
      结束时 `await store.aclose()`）；新增
      `platform_config_with_quota(tenant_id, quota_usd)` 辅助函数
      （基于既有 `platform_config` fixture 的租户列表，用
      `dataclasses.replace` 把指定租户替换为携带
      `daily_cost_quota_usd` 的版本）；新增
      `broken_audit_store()` 辅助——返回一个 `record()` 恒定抛出
      异常的 `AuditStore` 子类/包装实例，供"审计写入失败不影响原
      请求"测试使用

**Checkpoint**: fixture/辅助函数可被后续任务直接 import 使用

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 配置结构、异常、`AuditStore` 本体——所有用户故事的共同
依赖

**⚠️ CRITICAL**: 本阶段完成前任何用户故事不能开工

- [X] T002 扩展 src/platform_service/config.py：`TenantConfig` 新增
      可选字段 `daily_cost_quota_usd: float | None = None`（提供时
      `__post_init__` 校验 `> 0`）；`PlatformConfig` 新增
      `audit_db_path: str = "platform_audit.db"`；
      `load_config_from_file` 相应解析两者（均可选，缺省保持
      007-009 已有配置文件的向后兼容）
- [X] T003 [P] 扩展 src/platform_service/errors.py：新增
      `QuotaExceededError(tenant_id, quota_usd)`（独立于内核异常
      层级，同 `ConcurrencyLimitExceededError` 风格）
- [X] T004 [P] 创建 src/platform_service/audit.py：`AuditEntry`
      （frozen dataclass：`tenant_id`/`source`/`timestamp`/
      `input_tokens`/`output_tokens`/`cost_usd`/`status`）、
      `UsageSummary`（frozen dataclass：`tenant_id`/`start`/`end`/
      `request_count`/`total_input_tokens`/`total_output_tokens`/
      `total_cost_usd`）；`AuditStore(db_path: str)`——
      `_ensure_schema()`（首次操作前 `CREATE TABLE IF NOT EXISTS
      audit_entries (...)` + `tenant_id`/`timestamp` 索引，同
      `SqliteMemory` 的惰性建表风格）、
      `async def record(entry: AuditEntry) -> None`（单条 INSERT，
      异常正常向上抛，不做 best-effort 处理——由调用方决定，
      data-model.md）、
      `async def query_usage(tenant_id, start: datetime, end:
      datetime) -> UsageSummary`（`SELECT COUNT(*)/SUM(...)`，无
      匹配记录时返回全零汇总）、
      `async def sum_cost_since(tenant_id, since: datetime) ->
      float`（`SELECT COALESCE(SUM(cost_usd), 0)`）、
      `async def aclose() -> None`
- [X] T005 [P] 更新 src/platform_service/__init__.py：追加导出
      `AuditStore`、`AuditEntry`、`UsageSummary`、`QuotaExceededError`
- [X] T006 [P] 配置/审计存储单元测试
      tests/unit/platform_service/test_config.py（扩展）：
      `daily_cost_quota_usd` ≤0 拒绝、缺省为 `None`；
      `load_config_from_file` 不提供 `audit_db_path` 时默认为
      `"platform_audit.db"`；
      tests/unit/platform_service/test_audit.py（新建）：
      `record()` 后 `query_usage()` 返回的汇总（请求数/token/成本）
      与写入记录一致；`sum_cost_since()` 只统计窗口起点之后的记录
      （写入一条窗口外的记录，验证不计入）；无匹配记录的
      `query_usage()` 返回全零汇总（US2 验收场景 2）；用新
      `AuditStore` 实例指向同一 db 文件仍能查询到此前实例写入的
      记录（SC-003，持久化验证）

**Checkpoint**: `pytest tests/unit/platform_service/test_config.py
tests/unit/platform_service/test_audit.py` 全绿

---

## Phase 3: User Story 1 - 每次请求自动生成可追溯的用量/成本审计记录 (Priority: P1) 🎯 MVP

**Goal**: 无论经 REST/CLI/消息网关哪个入口，每次请求完成后都自动
写入一条包含租户、用量、成本、结果状态、来源入口的审计记录；审计
写入失败不影响原始请求结果

**Independent Test**: 分别经三个入口各发起一次请求（stub provider
驱动，覆盖成功与内核失败两种结果），验证每次都产生一条字段正确的
审计记录；用一个恒定失败的 `AuditStore` 驱动一次请求，验证原始请求
仍正常返回结果

- [ ] T007 [US1] 扩展 src/platform_service/agent_service.py：
      `build_agent_service()` 额外构造
      `AuditStore(config.audit_db_path)` 并传入
      `AgentService(..., audit_store=...)`；`AgentService.__init__`
      新增可选关键字参数 `audit_store: AuditStore | None = None`
      （默认 `None`，向后兼容 007-009 现有直接构造调用，
      research.md R2）；新增内部类 `_UsageTrackingProvider`——
      委托包装 `LLMProvider`，暴露同签名的
      `async def complete(self, request) -> LLMResponse`，转发
      调用并把每次响应的 `usage.input_tokens`/`usage.output_tokens`/
      `cost_usd` 累加到实例属性（`total_input_tokens`/
      `total_output_tokens`/`total_cost_usd`，初始为 0，
      research.md R1）；`handle()` 新增可选关键字参数
      `source: str = "unknown"`；`_handle_locked()` 内部：
      1) 用 `_UsageTrackingProvider(self._provider)` 包裹后传给
      本次调用新建的 `ReactEngine`（替换原先直接传入
      `self._provider`）；2)（原有流程不变，仍从 `engine.run()`
      获取 `answer`）；3) 成功返回前，若 `self._audit_store`
      非空，`try: await self._audit_store.record(AuditEntry(
      tenant_id=tenant_id, source=source,
      timestamp=当前 UTC 时间, input_tokens=包装器.
      total_input_tokens, output_tokens=..., cost_usd=...,
      status="success")) except Exception:
      logger.warning(..., exc_info=True)`（FR-003，不影响返回值）；
      4) `engine.run()` 抛出任何异常时，若 `self._audit_store`
      非空，同样 best-effort 记录 `status="failure"`（用量字段
      使用异常发生前包装器已累加的部分用量），随后重新抛出原异常
      （不改变对外可见的异常传播行为）
- [ ] T008 [US1] 在三个入口各自调用 `service.handle(...)` 的位置
      补充 `source` 参数：src/platform_service/app.py
      （`source="rest"`）、src/platform_service/cli.py
      （`source="cli"`）、src/platform_service/message_gateway.py
      （`source="message_gateway"`）
- [ ] T009 [P] [US1] AgentService 审计记录单元测试
      tests/unit/platform_service/test_agent_service.py（扩展）：
      成功调用后 `audit_store` 中有一条 `status="success"` 记录，
      `input_tokens`/`output_tokens`/`cost_usd` 与 stub provider
      的响应一致（验收场景 US1-1）；内核失败（`erroring_provider`）
      后仍写入一条 `status="failure"` 记录，且原异常正常向上抛出
      （验收场景 US1-2）；`audit_store=None`（不传，默认值）时
      调用行为与 007-009 既有版本完全一致，不抛任何审计相关异常
      （向后兼容性验证）；用 `broken_audit_store()` 驱动一次成功
      调用，验证 `handle()` 仍正常返回 `AgentRunResult`（验收
      场景 US1-3，`caplog` 断言产生一条警告日志）
- [ ] T010 [P] [US1] 在 tests/unit/platform_service/test_app_messages.py
      补充：一次成功的 `/v1/agent/run` 调用（注入真实
      `audit_store` fixture 的 `AgentService`）后，`audit_store`
      中存在一条 `source="rest"` 的记录
- [ ] T011 [P] [US1] 在 tests/unit/platform_service/test_cli.py
      补充：一次成功的 `cli.run()` 调用后，注入的 `audit_store`
      中存在一条 `source="cli"` 的记录
- [ ] T012 [P] [US1] 在 tests/unit/platform_service/test_message_gateway.py
      补充：一次成功的 `handle_inbound()` 调用后，注入的
      `audit_store` 中存在一条 `source="message_gateway"` 的记录

**Checkpoint**: US1 测试全绿——MVP 可演示（三个入口的每次请求都
产生正确的审计记录，审计写入失败不影响原始请求）

---

## Phase 4: User Story 2 - 运维方查询某租户的历史用量与成本汇总 (Priority: P2)

**Goal**: 提供一个按租户（限自身）与时间范围查询用量/成本汇总的
REST 接口

**Independent Test**: 用 US1 的方式产生若干条已知用量/成本的审计
记录，对覆盖这些记录时间戳的范围发起查询，验证返回的汇总与预期
一致；对无记录的时间范围查询，验证返回全零汇总而非错误

- [ ] T013 [US2] 在 src/platform_service/app.py 新增
      `GET /v1/audit/usage` 端点：读取 `X-API-Key` 请求头 →
      `resolve_tenant`（失败映射 401，复用既有逻辑）→ 解析可选
      query 参数 `start`/`end`（ISO8601 字符串，解析失败映射 422；
      缺省 `start` 为当日 UTC 零点、`end` 为当前时间，research.md
      R4）→ `await app.state.agent_service.audit_store.query_usage(
      tenant_id, start, end)` → 返回 `UsageSummary`；不接受调用方
      传入 `tenant_id` 参数（research.md R5/FR-005，查询范围永远是
      解析出的调用方自身租户）；需要将 `AgentService` 的
      `audit_store` 通过一个只读属性暴露（如
      `AgentService.audit_store` property）供 `app.py` 访问
- [ ] T014 [P] [US2] 创建 tests/unit/platform_service/test_app_audit.py：
      预先通过 `audit_store` 写入已知的若干条记录 → `GET
      /v1/audit/usage` 携带覆盖这些记录的 `start`/`end` → 验证
      返回汇总与预期一致（验收场景 US2-1）；查询一个无记录的时间
      范围 → 验证返回全零汇总而非错误（验收场景 US2-2）；缺失/
      非法 API Key → 401；`start`/`end` 格式非法 → 422；租户 A 的
      审计记录不会出现在租户 B 的查询结果里（验收场景 US2-3，
      隔离性验证）

**Checkpoint**: US1+US2 测试全绿——审计数据"可查询"能力具备

---

## Phase 5: User Story 3 - 租户成本配额超限时新请求被拒绝 (Priority: P3)

**Goal**: 为特定租户配置按天的成本配额，达到上限后新请求在触发任何
内核调用之前即被拒绝；未配置配额的租户不受影响

**Independent Test**: 为某租户配置一个很小的成本配额，用 stub
provider 驱动若干次请求使累计成本达到配额，再发起下一次请求，验证
被拒绝且未触发任何内核调用（哨兵 provider 验证）；未配置配额的租户
不受影响

- [ ] T015 [US3]（`/speckit-analyze` F1 修正后的设计）在
      src/platform_service/agent_service.py 新增内部类
      `QuotaLockRegistry`（与既有 `SessionLockRegistry` 完全同
      写法，按 `tenant_id` 惰性创建/复用 `asyncio.Lock`）；改造
      `handle()`：若 `self._audit_store is not None` 且租户配置了
      `daily_cost_quota_usd`，用
      `self._quota_locks.get_lock(tenant_id)` 把"配额检查 → 会话锁
      获取（如适用）→ `_handle_locked()` 全部内容"整段包裹在
      `async with` 内（固定加锁顺序：先配额锁，再会话锁，
      data-model.md"并发下的配额一致性"）；两个前提任一不满足时
      完全不加锁，直接走原有路径（FR-006/SC-006，零开销）；在
      `_handle_locked()` 起始处（此时已持有配额锁，读到的数据是
      最新的）新增实际检查：
      `await self._audit_store.sum_cost_since(tenant_id, 当日 UTC
      零点)` 达到或超过配额时抛
      `QuotaExceededError(tenant_id, quota_usd)`（在加载会话历史/
      构造 `ReactEngine` 之前，不触发任何内核调用，FR-007）
- [ ] T016 [US3] 在 src/platform_service/app.py 的 `/v1/agent/run`
      端点新增 `except QuotaExceededError` 分支——
      `span.set_result("quota_exceeded")`，映射 HTTP 402（区别于
      429/502/504，contracts/audit-api.md）
- [ ] T017 [P] [US3] 在 src/platform_service/cli.py 新增退出码常量
      `EXIT_QUOTA_EXCEEDED = 7`（追加，不重排 008 已发布的既有
      数值）；`run()` 新增 `except QuotaExceededError` 分支
- [ ] T018 [P] [US3] 在 src/platform_service/message_gateway.py 的
      `_process_and_callback()` 新增 `except QuotaExceededError`
      分支——出站回调 payload `status="quota_exceeded"`（复用既有
      `status`/`error` 字段结构）
- [ ] T019 [P] [US3] 在 tests/unit/platform_service/test_agent_service.py
      补充：用 `platform_config_with_quota` 与预先写入的审计记录
      使某租户当日累计成本达到配额，验证 `handle()` 抛
      `QuotaExceededError`，且断言 stub provider/`ReactEngine`
      从未被调用（用会在被调用时抛出断言错误的哨兵 provider，
      验收场景 US3-1）；未配置配额的租户不受影响（验收场景
      US3-2）；写入一条配额窗口**之外**（如昨天）的高成本记录，
      验证今日窗口内请求不受影响（验收场景 US3-3，窗口重置验证）；
      **并发一致性回归测试（`/speckit-analyze` F1）**：为一个配置了
      `daily_cost_quota_usd`（如设为略高于单次调用成本、低于两次
      调用成本之和）的租户，用 `slow_stub_provider` 同时发起两个
      并发的 `handle()` 调用（`asyncio.gather`），验证二者不会同时
      通过配额检查——即最终只有一次成功写入 `status="success"` 的
      审计记录、另一次收到 `QuotaExceededError`，而不是两次都成功
      导致累计成本超过配额（验证 `QuotaLockRegistry` 确实生效，
      而不仅仅是"读时加锁"这种仍会放行的弱修复）；
      **口径一致性回归测试（`/speckit-analyze` F2）**：写入若干条
      审计记录后，断言 `audit_store.sum_cost_since(tenant_id,
      窗口起点)` 与 `audit_store.query_usage(tenant_id, 窗口起点,
      now).total_cost_usd` 两者数值相等（SC-007，证明配额检查与
      查询端点确实共享同一份数据、口径一致）
- [ ] T020 [P] [US3] 在 tests/unit/platform_service/test_app_audit.py
      补充：租户当日累计成本达到配额后，`/v1/agent/run` 返回 402
- [ ] T021 [P] [US3] 在 tests/unit/platform_service/test_cli.py
      补充：配额超限场景返回 `EXIT_QUOTA_EXCEEDED`
- [ ] T022 [P] [US3] 在 tests/unit/platform_service/test_message_gateway.py
      补充：配额超限场景的出站回调 `status="quota_exceeded"`

**Checkpoint**: US1-US3 测试全绿——审计记录、查询、配额强化三项
能力全部具备，且始终共享同一份数据（FR-008）

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 示例配置、演示脚本、文档收尾与最终验证

- [ ] T023 [P] 扩展 examples/platform_config.example.json：新增
      `audit_db_path` 字段与至少一个租户的 `daily_cost_quota_usd`
      字段示例
- [ ] T024 [P] 创建演示脚本 examples/demo_audit.py：复用 T023 的
      示例配置结构（provider 替换为 stub），依次演示：一次成功调用
      产生审计记录 → 查询该租户的用量汇总 → 反复调用耗尽配额后
      新请求被拒绝，打印每一步的关键输出
- [ ] T025 按 quickstart.md 全流程验证：
      `pytest tests/unit/platform_service -v` 全绿（含新增的
      `test_audit.py`/`test_app_audit.py`）→ demo 脚本输出符合
      预期 → 修复发现的问题
- [ ] T026 更新 README.md roadmap：010 状态改为"✅ 已完成"；更新
      examples/README.md 追加 `demo_audit.py` 条目

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 → Phase 2 → 用户故事**：严格顺序
- **US1**：依赖 Phase 2 全部任务，是 US2/US3 的数据基础
  （`AuditStore`/审计记录写入均在 US1 建立）
- **US2**：依赖 US1 已产生的审计记录（查询接口只读，不修改 US1
  建立的写入路径）
- **US3**：依赖 US1 的 `AuditStore` 集成（配额检查复用同一份数据，
  FR-008），与 US2 相互独立（配额检查不经过查询端点）
- **Phase 6**：依赖 US1-US3 全部完成

### Parallel Opportunities

- Phase 2 内：T003/T004/T005 可并行（T002 独立）；T006 依赖
  T002/T004
- US1 内：T009/T010/T011/T012 可并行编写（不同文件，均依赖
  T007/T008）
- US2 内：T014 单任务，依赖 T013
- US3 内：T017/T018 可并行（T015 先行）；T019/T020/T021/T022
  可并行编写（不同文件，均依赖对应实现任务）
- Phase 6：T023/T024 可并行；T025 依赖 T024；T026 依赖 T025

## Implementation Strategy

**MVP = Phase 1 + 2 + US1**（T001-T012）：三个入口的每次请求都
自动产生正确、持久化、最佳努力的审计记录，即可演示核心价值（"用量/
成本可追溯"）。随后 US2（查询汇总）→ US3（配额强化）递增交付，
两者都直接复用 US1 建立的同一份 `AuditStore` 数据，不引入任何第二套
统计口径。最后 Polish 补齐示例配置、演示脚本与文档。每个 Checkpoint
处 `pytest` 必须全绿再前进。
